"""Problem of the Day: the daily post, its buttons, the /potd commands and the scheduler loop.

Everything private (hints, answer checking, solutions) happens through ephemeral replies, so nothing is ever
spoiled in the channel. The buttons use fixed custom IDs and look the problem up by message ID, so they keep
working across bot restarts.
"""
from __future__ import annotations

import asyncio
import io
import logging
import zoneinfo
from datetime import date, datetime, timedelta, timezone as dt_timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from math_engine.errors import MathError
from services.potd import (AlreadyPostedError, HintStatus, PreparedPost, RevealStatus, SettingsError, SubmitResult,
                           SubmitStatus)
from services.problem_bank import LEVEL_BLURBS, Problem

from .formatting import clean_inline
from .membership import is_member, missing_permissions, not_a_member_message

log = logging.getLogger(__name__)

LEVEL_COLORS = {"core": 0x2ECC71, "advanced": 0x3498DB, "challenge": 0xE74C3C}
BACKOFF = timedelta(minutes=15)           # after a failed send, leave that server alone for a while
_TIMEZONES = sorted(zoneinfo.available_timezones())


def utcnow() -> datetime:
    return datetime.now(dt_timezone.utc)


# ---------------------------------------------------------------------------------------------- pure formatting

def problem_embed(problem: Problem, day: date, *, image: bool, latex_fallback: str | None = None) -> discord.Embed:
    embed = discord.Embed(title=f"Problem of the Day: {problem.title}", description=problem.statement_text,
                          color=LEVEL_COLORS[problem.level])
    embed.set_author(name=f"{day:%A}, {day:%B} {day.day}, {day.year}")
    embed.add_field(name="Subject", value=problem.subject_label)
    embed.add_field(name="Level", value=f"{problem.level_label} ({LEVEL_BLURBS[problem.level]})")
    if image:
        embed.set_image(url="attachment://problem.png")
    elif latex_fallback:
        embed.add_field(name="Formula (LaTeX)", value=f"```\n{latex_fallback}\n```"[:1024], inline=False)
    embed.set_footer(text="Hints, answers and solutions are private to you.")
    return embed


def solution_embed(problem: Problem, *, forfeited: bool = False) -> discord.Embed:
    embed = discord.Embed(title=f"Solution: {problem.title}", color=LEVEL_COLORS[problem.level],
                          description=f"**Answer:** {problem.answer_display}\n\n{problem.solution}")
    if forfeited:
        embed.set_footer(text="You viewed the solution before solving, so this problem no longer counts for you.")
    return embed


def submit_message(r: SubmitResult) -> str:
    s = SubmitStatus
    if r.status is s.CORRECT:
        tries = "on your first try" if r.attempts == 1 else f"in {r.attempts} attempts"
        days = f"{r.streak} problem{'s' if r.streak != 1 else ''} in a row" if r.streak else ""
        return f"✅ **Correct!** Solved {tries}." + (f" 🔥 Streak: {days}." if r.streak > 1 else "")
    if r.status is s.INCORRECT:
        left = "" if r.attempts_left is None else f" You have {r.attempts_left} attempt{'s' if r.attempts_left != 1 else ''} left."
        return f"❌ Not quite.{left}\n*Format: {r.problem.answer_format}.* The 💡 Hint button can help."
    if r.status is s.INVALID:
        return f"⚠️ {clean_inline(r.message or 'That answer could not be read.', 400)}\n*This did not count as an attempt.*"
    if r.status is s.ALREADY_SOLVED:
        return "🎉 You have already solved this problem."
    if r.status is s.REVEALED:
        return "📖 You viewed the solution, so this problem can no longer be submitted for credit."
    if r.status is s.CLOSED:
        return "🔒 This problem's day has ended, so answers are closed. You can still view the solution."
    if r.status is s.COOLDOWN:
        return f"⏳ Please wait {max(1, round(r.retry_after))} more seconds before trying again."
    if r.status is s.OUT_OF_ATTEMPTS:
        return f"🚫 You have used all {r.attempts} attempts for this problem. You can still view the solution."
    if r.status is s.ERROR:
        return f"⚠️ {clean_inline(r.message or 'The answer could not be checked right now.', 300)}\n*This did not count as an attempt.*"
    return "This problem is no longer available."


def describe_settings(s, next_post: datetime | None) -> str:
    where = f"<#{s.channel_id}>" if s.channel_id else "*not set*"
    status = "✅ enabled" if s.enabled else "⏸️ paused"
    lines = [f"**Problem of the Day:** {status}", f"**Channel:** {where}",
             f"**Time:** {s.hour:02d}:{s.minute:02d} ({s.timezone})", f"**Difficulty:** {s.difficulty}",
             f"**No repeats within:** {s.repeat_window_days} days"]
    if s.enabled and next_post:
        lines.append(f"**Next post:** <t:{int(next_post.timestamp())}:F>")
    return "\n".join(lines)


# ---------------------------------------------------------------------------------------------- views

class PotdView(discord.ui.View):
    """Persistent buttons under every daily post. Fixed custom IDs; the post is found from the message ID."""

    def __init__(self, cog: "Potd") -> None:
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Hint", emoji="💡", style=discord.ButtonStyle.secondary, custom_id="potd:hint")
    async def hint(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog.on_hint(interaction)

    @discord.ui.button(label="Submit answer", emoji="✏️", style=discord.ButtonStyle.primary, custom_id="potd:answer")
    async def answer(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog.on_answer(interaction)

    @discord.ui.button(label="Solution", emoji="📖", style=discord.ButtonStyle.secondary, custom_id="potd:solution")
    async def solution(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog.on_solution(interaction)


class AnswerModal(discord.ui.Modal, title="Submit your answer"):
    answer = discord.ui.TextInput(label="Your answer", max_length=200, required=True)

    def __init__(self, cog: "Potd", message_id: int, problem: Problem) -> None:
        super().__init__()
        self.cog, self.message_id = cog, message_id
        # Only the placeholder is customised: changing .label after construction is deprecated in discord.py 2.7.
        if problem.answer_type == "choice":
            self.answer.placeholder = f"One letter: {', '.join(problem.option_letters)}"
        else:
            self.answer.placeholder = problem.answer_format[:100]

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.handle_submission(interaction, self.message_id, self.answer.value)

    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        log.exception("Error in the answer form", exc_info=error)
        await self.cog.reply(interaction, "⚠️ Something went wrong on my side. It has been logged.")


class ConfirmRevealView(discord.ui.View):
    def __init__(self, cog: "Potd", message_id: int) -> None:
        super().__init__(timeout=120)
        self.cog, self.message_id = cog, message_id

    @discord.ui.button(label="Show the solution anyway", style=discord.ButtonStyle.danger)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await self.cog.on_confirm_reveal(interaction, self.message_id)


# ---------------------------------------------------------------------------------------------- the cog

class Potd(commands.Cog):
    potd = app_commands.Group(name="potd", description="Problem of the Day", guild_only=True)

    def __init__(self, bot, service, renderer, clock=utcnow) -> None:
        self.bot, self.service, self.renderer, self.clock = bot, service, renderer, clock
        self._backoff: dict[int, datetime] = {}
        self._last_error: dict[int, str] = {}          # why the most recent post attempt failed, shown by /potd status

    async def cog_load(self) -> None:
        self.bot.add_view(PotdView(self))          # re-attach the buttons of every existing post after a restart
        self.tick.start()

    async def cog_unload(self) -> None:
        self.tick.cancel()

    @staticmethod
    async def reply(interaction: discord.Interaction, text: str, **kwargs) -> None:
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True, **kwargs)
        else:
            await interaction.response.send_message(text, ephemeral=True, **kwargs)

    # ------------------------------------------------------------------------------------ scheduler

    @tasks.loop(minutes=1)
    async def tick(self) -> None:
        await self.run_due(self.clock())

    @tick.before_loop
    async def _before_tick(self) -> None:
        await self.bot.wait_until_ready()

    async def run_due(self, now: datetime) -> int:
        """Post everything that is due. Returns how many posts were sent. Never raises (it runs in a loop)."""
        skip = {guild for guild, until in self._backoff.items() if until > now}
        try:
            prepared = await self.service.due_posts(now, skip)
        except Exception:  # noqa: BLE001 - a scheduler error must not kill the loop
            log.exception("Problem of the Day scheduler failed")
            return 0
        sent = 0
        for item in prepared:
            if await self._send_prepared(item):
                sent += 1
                self._backoff.pop(item.post.guild_id, None)
            else:
                self._backoff[item.post.guild_id] = now + BACKOFF
        return sent

    async def _build_message(self, problem: Problem, day: date):
        picture, fallback = None, None
        if problem.display:
            try:
                if self.renderer is None:
                    raise MathError("no renderer")
                png = await self.renderer.render(problem.display, max_length=1000)
                picture = discord.File(io.BytesIO(png), filename="problem.png", description=problem.display[:1000])
            except MathError as exc:
                log.warning("Could not typeset %s (%s); showing LaTeX source instead", problem.id, exc)
                fallback = problem.display
        return problem_embed(problem, day, image=picture is not None, latex_fallback=fallback), picture

    def _client_id(self) -> int | None:
        return getattr(self.bot, "application_id", None) or getattr(getattr(self.bot, "user", None), "id", None)

    async def _give_up(self, post, reason: str) -> bool:
        """Release the claim (so a later attempt can retry), remember WHY for /potd status, and report failure."""
        log.warning("Problem of the Day: guild %s: %s", post.guild_id, reason)
        self._last_error[post.guild_id] = reason
        await self.service.abandon_post(post.id)
        return False

    async def _send_prepared(self, item: PreparedPost) -> bool:
        """Send a claimed post. On failure the claim is released so a later attempt can retry."""
        post, problem = item.post, item.problem
        where = f"<#{post.channel_id}>"
        channel = self.bot.get_channel(post.channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(post.channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                channel = None
        if channel is None:
            return await self._give_up(
                post, f"I cannot see {where}. If it is private, allow my role to view it; if I do not appear in the "
                      "server's member list, I was added without the bot scope and need the link from /invite.")
        missing = missing_permissions(channel, getattr(channel, "guild", None))
        if missing:
            return await self._give_up(
                post, f"I am missing these permissions in {where}: {', '.join(missing)}. Give my role those permissions there.")

        embed, picture = await self._build_message(problem, post.post_date)
        try:
            message = await channel.send(embed=embed, view=PotdView(self), **({"file": picture} if picture else {}))
        except (discord.Forbidden, discord.HTTPException) as exc:
            return await self._give_up(
                post, f"Discord would not let me post in {where} ({getattr(exc, 'text', None) or exc}). "
                      "Check my permissions in that channel.")
        for attempt in (1, 2):                      # the message exists now: do not lose track of it
            try:
                await self.service.complete_post(post.id, message.id)
                break
            except Exception:  # noqa: BLE001
                log.exception("Could not record message %s for post %s (attempt %s)", message.id, post.id, attempt)
                await asyncio.sleep(0.5)
        self._last_error.pop(post.guild_id, None)
        self.bot.latest_problem_title = problem.title           # the status can show it (the title never gives anything away)
        log.info("Posted %s to guild %s", problem.id, post.guild_id)
        return True

    # ------------------------------------------------------------------------------------ button handlers

    async def on_hint(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        r = await self.service.hint(interaction.message.id, interaction.user.id, self.clock())
        if r.status is HintStatus.OK:
            text = f"💡 **Hint {r.number} of {r.total}**\n{r.text}" + ("" if r.number < r.total else "\n*That was the last hint.*")
        elif r.status is HintStatus.NO_MORE:
            text = f"You have seen all {r.total} hints. The last one was:\n{r.text}"
        elif r.status is HintStatus.NO_HINTS:
            text = "This problem has no hints."
        else:
            text = "This problem is no longer available."
        await interaction.followup.send(text, ephemeral=True)

    async def on_answer(self, interaction: discord.Interaction) -> None:
        ctx = await self.service.context(interaction.message.id, self.clock())
        if ctx is None:
            await self.reply(interaction, "This problem is no longer available.")
        elif not ctx.is_open:
            await self.reply(interaction, submit_message(SubmitResult(SubmitStatus.CLOSED, problem=ctx.problem)))
        else:
            await interaction.response.send_modal(AnswerModal(self, interaction.message.id, ctx.problem))

    async def handle_submission(self, interaction: discord.Interaction, message_id: int, text: str) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        result = await self.service.submit(message_id, interaction.user.id, text, self.clock())
        await interaction.followup.send(submit_message(result), ephemeral=True)

    async def on_solution(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        r = await self.service.reveal(interaction.message.id, interaction.user.id, self.clock())
        if r.status is RevealStatus.UNAVAILABLE:
            await interaction.followup.send("This problem is no longer available.", ephemeral=True)
        elif r.status is RevealStatus.CONFIRM_NEEDED:
            await interaction.followup.send(
                "⚠️ **Viewing the solution before you have solved the problem means it will not count for you** "
                "(no credit, and it will not extend your streak). Show it anyway?",
                view=ConfirmRevealView(self, interaction.message.id), ephemeral=True)
        else:
            await interaction.followup.send(embed=solution_embed(r.problem), ephemeral=True)

    async def on_confirm_reveal(self, interaction: discord.Interaction, message_id: int) -> None:
        r = await self.service.reveal(message_id, interaction.user.id, self.clock(), confirmed=True)
        await interaction.response.edit_message(content="Solution below.", view=None)
        if r.status is RevealStatus.SHOWN:
            await interaction.followup.send(embed=solution_embed(r.problem, forfeited=r.forfeited), ephemeral=True)
        else:
            await interaction.followup.send("This problem is no longer available.", ephemeral=True)

    # ------------------------------------------------------------------------------------ commands

    async def _timezone_choices(self, interaction: discord.Interaction, current: str) -> list[app_commands.Choice[str]]:
        needle = current.lower().replace(" ", "_")
        return [app_commands.Choice(name=n, value=n) for n in _TIMEZONES if needle in n.lower()][:25]

    @potd.command(name="setup", description="Configure the daily problem (requires Manage Server)")
    @app_commands.describe(
        channel="Where to post", hour="Hour of day to post, 0-23 (server's timezone)", minute="Minute, 0-59",
        timezone="Timezone name, e.g. America/Toronto", difficulty="Which problems to post",
        enabled="Turn daily posting on or off", repeat_days="Do not repeat a problem within this many days")
    @app_commands.choices(difficulty=[
        app_commands.Choice(name="any (a mix of all levels)", value="any"),
        app_commands.Choice(name="core (upper-division course material)", value="core"),
        app_commands.Choice(name="advanced (competition-style)", value="advanced"),
        app_commands.Choice(name="challenge (hard)", value="challenge"),
    ])
    @app_commands.autocomplete(timezone=_timezone_choices)
    @app_commands.checks.has_permissions(manage_guild=True)
    async def potd_setup(self, interaction: discord.Interaction, channel: Optional[discord.TextChannel] = None,
                         hour: Optional[app_commands.Range[int, 0, 23]] = None,
                         minute: Optional[app_commands.Range[int, 0, 59]] = None, timezone: Optional[str] = None,
                         difficulty: Optional[str] = None, enabled: Optional[bool] = None,
                         repeat_days: Optional[app_commands.Range[int, 1, 365]] = None) -> None:
        try:
            settings = await self.service.update_settings(
                interaction.guild_id, channel_id=channel.id if channel else None, hour=hour, minute=minute,
                timezone=timezone, difficulty=difficulty, enabled=enabled, repeat_window_days=repeat_days)
        except SettingsError as exc:
            await self.reply(interaction, f"❌ {exc}")
            return
        text = describe_settings(settings, await self.service.next_post_at(settings, self.clock()) if settings.enabled else None)
        target = channel or (self.bot.get_channel(settings.channel_id) if settings.channel_id else None)
        if not is_member(interaction.guild):
            text += "\n\n" + not_a_member_message(self._client_id())
        else:
            missing = missing_permissions(target, interaction.guild)
            if missing:
                text += f"\n\n⚠️ I am missing these permissions in that channel: **{', '.join(missing)}**."
        await self.reply(interaction, "Saved.\n\n" + text)

    @potd.command(name="status", description="Show the Problem of the Day settings for this server")
    async def potd_status(self, interaction: discord.Interaction) -> None:
        settings = await self.service.get_settings(interaction.guild_id)
        text = describe_settings(settings, await self.service.next_post_at(settings, self.clock()) if settings.enabled else None)
        bank = self.service.bank
        text += f"\n**Server membership:** {'✅ I am a member of this server' if is_member(interaction.guild) else '⚠️ not a member (see below)'}"
        error = self._last_error.get(interaction.guild_id)
        if error:
            text += f"\n**Last post problem:** {error}"
        text += f"\n\n**Problem bank:** {len(bank)} problems ({', '.join(f'{len(bank.by_level(lv))} {lv}' for lv in LEVEL_BLURBS)})"
        if not is_member(interaction.guild):
            text += "\n\n" + not_a_member_message(self._client_id())
        await self.reply(interaction, text)

    @potd.command(name="post", description="Post today's problem now (requires Manage Server)")
    @app_commands.describe(replace="If today's problem was already posted, discard it (and everyone's progress) and post a new one")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def potd_post(self, interaction: discord.Interaction, replace: bool = False) -> None:
        await interaction.response.defer(ephemeral=True)
        settings = await self.service.get_settings(interaction.guild_id)
        channel_id = settings.channel_id or interaction.channel_id
        try:
            item = await self.service.post_now(interaction.guild_id, channel_id, self.clock(), replace=replace)
        except AlreadyPostedError:
            await interaction.followup.send(
                "A problem was already posted for today. Use `replace: True` to discard it and post a new one "
                "(this deletes everyone's progress on it).", ephemeral=True)
            return
        if await self._send_prepared(item):
            await interaction.followup.send(f"Posted in <#{channel_id}>.", ephemeral=True)
        else:
            reason = self._last_error.get(interaction.guild_id) or \
                "Check that I can view the channel, send messages, embed links and attach files."
            extra = "" if is_member(interaction.guild) else "\n\n" + not_a_member_message(self._client_id())
            await interaction.followup.send(f"❌ I could not post there. {reason}{extra}", ephemeral=True)

    @potd.command(name="stats", description="Your Problem of the Day record")
    @app_commands.describe(user="Whose record to show (default: yours)")
    async def potd_stats(self, interaction: discord.Interaction, user: Optional[discord.Member] = None) -> None:
        target = user or interaction.user
        s = await self.service.stats(interaction.guild_id, target.id, self.clock())
        lines = [f"**Solved:** {s.solved} of {s.total_posts} problems posted",
                 f"**Current streak:** {s.current_streak} · **Best streak:** {s.best_streak}",
                 f"**Solved without hints:** {s.solved_without_hints}"]
        if s.by_subject:
            lines.append("**By subject:** " + ", ".join(f"{k} {v}" for k, v in sorted(s.by_subject.items())))
        embed = discord.Embed(title=f"Problem of the Day: {getattr(target, 'display_name', target.id)}",
                              description="\n".join(lines), color=0x3498DB)
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @potd.command(name="leaderboard", description="Top solvers in this server")
    async def potd_leaderboard(self, interaction: discord.Interaction) -> None:
        rows = await self.service.leaderboard(interaction.guild_id, self.clock(), limit=10)
        if not rows:
            await interaction.response.send_message("Nobody has solved a problem here yet.", ephemeral=True)
            return
        lines = [f"**{r.rank}.** <@{r.user_id}>: {r.solved} solved · best streak {r.best_streak} (current {r.current_streak})"
                 for r in rows]
        await interaction.response.send_message(
            embed=discord.Embed(title="Problem of the Day leaderboard", description="\n".join(lines), color=0xF1C40F),
            ephemeral=True)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            message = "You need the **Manage Server** permission to do that."
        else:
            log.exception("Unhandled error in /potd", exc_info=error)
            message = "⚠️ Something went wrong on my side. It has been logged."
        await self.reply(interaction, message)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Potd(bot, bot.potd_service, bot.renderer))  # type: ignore[attr-defined]
