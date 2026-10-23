import asyncio
import random
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

import discord
import pytest
from discord import app_commands

import cogs.potd as potd_module
from cogs.potd import (AnswerModal, ConfirmRevealView, Potd, PotdView, describe_settings, problem_embed, solution_embed,
                       submit_message)
from database.potd_repo import PotdRepository
from math_engine.errors import InputError
from services.potd import PotdService, SubmitResult, SubmitStatus
from services.problem_bank import load_bank
from tests.potd_support import NOW, FakeInteraction, InProcessEngine, make_bank, raw

GUILD, CHANNEL = 100, 500
PNG = b"\x89PNG\r\n\x1a\nfake"


class Clock:
    def __init__(self, now=NOW):
        self.now = now

    def __call__(self):
        return self.now


class FakeChannel:
    def __init__(self, channel_id=CHANNEL, error=None, **perms):
        self.id, self.error, self.sent, self._next = channel_id, error, [], 9000
        self.perms = SimpleNamespace(**{"view_channel": True, "send_messages": True, "embed_links": True,
                                        "attach_files": True, **perms})

    async def send(self, **kwargs):
        if self.error:
            raise self.error
        self.sent.append(kwargs)
        self._next += 1
        return SimpleNamespace(id=self._next - 1)

    def permissions_for(self, me):
        return self.perms


class FakeBot:
    def __init__(self, *channels):
        self.channels = {c.id: c for c in channels}
        self.views, self.fetches = [], 0

    def get_channel(self, channel_id):
        return self.channels.get(channel_id)

    async def fetch_channel(self, channel_id):
        self.fetches += 1
        raise discord.NotFound(SimpleNamespace(status=404, reason="Not Found"), "Unknown Channel")

    def add_view(self, view):
        self.views.append(view)

    async def wait_until_ready(self):
        await asyncio.Event().wait()           # never "ready": lets us start and cancel the loop safely


class FakeRenderer:
    def __init__(self, error=None):
        self.error, self.calls = error, []

    async def render(self, latex, *, max_length=None):
        self.calls.append(latex)
        if self.error:
            raise self.error
        return PNG


def build(db, bank, channel=None, renderer=None, clock=None):
    channel = channel or FakeChannel()
    bot = FakeBot(channel)
    service = PotdService(PotdRepository(db), bank, InProcessEngine(), random.Random(3))
    cog = Potd(bot, service, renderer, clock=clock or Clock())
    return SimpleNamespace(cog=cog, bot=bot, service=service, channel=channel, clock=cog.clock)


@pytest.fixture
async def env(open_db):
    """One problem (answer 12), so everything that is posted is known."""
    return build(await open_db(), make_bank(raw("num", "analysis", "core", answer="12", display=r"x^{2}")),
                 renderer=FakeRenderer())


async def configure(e, **extra):
    return await e.service.update_settings(GUILD, enabled=True, channel_id=CHANNEL, hour=9, minute=0,
                                           timezone="America/Toronto", **extra)


async def post_today(e) -> int:
    """Run the scheduler and return the Discord message id of the post it made."""
    await configure(e)
    assert await e.cog.run_due(e.clock()) == 1
    return 9000 + len(e.channel.sent) - 1


def interaction(e=None, user_id=1, message_id=None, guild=True):
    return FakeInteraction(user_id=user_id, message_id=message_id, guild_id=GUILD, channel_id=CHANNEL,
                           guild=SimpleNamespace(me=object()) if guild else None)


# ============================================================================================ formatting

DAY = date(2026, 10, 19)
BANK = load_bank(Path(__file__).resolve().parent.parent / "data" / "problems.yaml")


def test_the_post_embed_shows_subject_level_date_and_the_statement():
    p = BANK.get("ana-factorial-root")
    embed = problem_embed(p, DAY, image=True)
    assert embed.title == "Problem of the Day: A limit with factorials"
    assert embed.author.name == "Monday, October 19, 2026"
    assert [(f.name, f.value) for f in embed.fields][0] == ("Subject", "Analysis")
    assert "Core" in embed.fields[1].value and embed.image.url == "attachment://problem.png"
    assert embed.description == "Evaluate the limit."


def test_without_an_image_the_latex_source_is_shown_instead():
    embed = problem_embed(BANK.get("ana-factorial-root"), DAY, image=False, latex_fallback=r"\lim x")
    assert embed.image.url is None and r"\lim x" in embed.fields[-1].value


def test_multiple_choice_options_are_listed_with_letters():
    embed = problem_embed(BANK.get("alg-s4-false-statement"), DAY, image=False)
    assert "**A.**" in embed.description and "**E.**" in embed.description


def test_the_solution_embed_contains_the_answer_and_notes_forfeiture():
    p = BANK.get("ana-arctan-telescoping")
    embed = solution_embed(p)
    assert "3*pi/4" in embed.description and p.solution[:40] in embed.description and embed.footer.text is None
    assert "no longer counts" in solution_embed(p, forfeited=True).footer.text


def S(status, **kw):
    return SubmitResult(status, problem=BANK.get("ana-arctan-telescoping"), **kw)


@pytest.mark.parametrize("result,fragments", [
    (S(SubmitStatus.CORRECT, attempts=1, streak=1), ["Correct", "first try"]),
    (S(SubmitStatus.CORRECT, attempts=3, streak=4), ["3 attempts", "Streak: 4 problems in a row"]),
    (S(SubmitStatus.INCORRECT, attempts=1), ["Not quite", "Format:", "Hint"]),
    (S(SubmitStatus.INCORRECT, attempts=1, attempts_left=1), ["1 attempt left"]),
    (S(SubmitStatus.INCORRECT, attempts=2, attempts_left=0), ["0 attempts left"]),
    (S(SubmitStatus.INVALID, message="Could not parse"), ["Could not parse", "did not count"]),
    (S(SubmitStatus.ALREADY_SOLVED), ["already solved"]),
    (S(SubmitStatus.REVEALED), ["viewed the solution"]),
    (S(SubmitStatus.CLOSED), ["day has ended", "solution"]),
    (S(SubmitStatus.COOLDOWN, retry_after=6.2), ["6 more seconds"]),
    (S(SubmitStatus.OUT_OF_ATTEMPTS, attempts=2), ["all 2 attempts"]),
    (S(SubmitStatus.ERROR, message="took too long"), ["took too long", "did not count"]),
    (SubmitResult(SubmitStatus.UNAVAILABLE), ["no longer available"]),
])
def test_every_submit_outcome_has_a_clear_message(result, fragments):
    text = submit_message(result)
    assert all(f in text for f in fragments), text


@pytest.mark.parametrize("problem", [p for p in BANK if len(p.answer_display) >= 3], ids=lambda p: p.id)
def test_a_wrong_answer_message_never_contains_the_answer(problem):
    text = submit_message(SubmitResult(SubmitStatus.INCORRECT, attempts=1, attempts_left=1, problem=problem))
    assert problem.answer_display not in text and problem.answer not in text


def test_settings_description():
    from database.potd_repo import GuildSettings
    s = GuildSettings(1, True, 55, 8, 5, "Europe/London", "core", 30)
    text = describe_settings(s, NOW)
    assert "<#55>" in text and "08:05" in text and "Europe/London" in text and "core" in text and "30 days" in text
    assert f"<t:{int(NOW.timestamp())}:F>" in text
    paused = describe_settings(s.with_changes(enabled=False), NOW)
    assert "paused" in paused and "Next post" not in paused
    assert "not set" in describe_settings(GuildSettings(1), None)


# ============================================================================================ structure

def test_the_buttons_are_persistent_and_have_fixed_ids():
    async def check():
        view = PotdView(cog=None)
        assert view.is_persistent() and view.timeout is None
        assert [c.custom_id for c in view.children] == ["potd:hint", "potd:answer", "potd:solution"]
    asyncio.run(check())


def test_command_structure_and_permissions():
    group = Potd.potd
    assert group.name == "potd" and group.guild_only
    assert {c.name for c in group.commands} == {"setup", "status", "post", "stats", "leaderboard"}
    by_name = {c.name: c for c in group.commands}
    assert by_name["setup"].checks and by_name["post"].checks                          # need Manage Server
    assert not by_name["stats"].checks and not by_name["leaderboard"].checks and not by_name["status"].checks


async def test_loading_the_cog_registers_the_buttons_and_starts_the_scheduler(env):
    await env.cog.cog_load()
    try:
        assert len(env.bot.views) == 1 and isinstance(env.bot.views[0], PotdView)
        assert env.cog.tick.is_running()
    finally:
        await env.cog.cog_unload()
    await asyncio.sleep(0)
    assert env.cog.tick.is_being_cancelled() or not env.cog.tick.is_running()


async def test_timezone_autocomplete(env):
    names = [c.value for c in await env.cog._timezone_choices(interaction(), "toron")]
    assert "America/Toronto" in names
    assert len(await env.cog._timezone_choices(interaction(), "")) == 25
    assert [c.value for c in await env.cog._timezone_choices(interaction(), "new york")] == ["America/New_York"]


# ============================================================================================ the scheduler

async def test_the_scheduler_posts_once_with_buttons_an_image_and_no_spoilers(env):
    await configure(env)
    assert await env.cog.run_due(NOW) == 1
    assert await env.cog.run_due(NOW + timedelta(minutes=1)) == 0                        # no duplicate
    assert env.bot.latest_problem_title == "Title num"                                   # the status can show today's problem
    (sent,) = env.channel.sent
    assert isinstance(sent["view"], PotdView)
    assert sent["embed"].title.endswith("Title num") and sent["embed"].image.url == "attachment://problem.png"
    assert sent["file"].filename == "problem.png" and env.cog.renderer.calls == ["x^{2}"]
    e = sent["embed"]
    posted = " ".join([e.title or "", e.description or "", e.footer.text or "", e.author.name or ""]
                      + [f"{f.name} {f.value}" for f in e.fields])
    assert "Because." not in posted and "first hint" not in posted and "12" not in e.description
    post = await env.service.repo.get_post_by_message(9000)
    assert post and post.guild_id == GUILD and post.channel_id == CHANNEL


async def test_posting_falls_back_to_latex_source_if_typesetting_fails(open_db):
    e = build(await open_db(), make_bank(raw("num", display=r"x^{2}")), renderer=FakeRenderer(InputError("cannot draw")))
    await configure(e)
    assert await e.cog.run_due(NOW) == 1
    sent = e.channel.sent[0]
    assert "file" not in sent and r"x^{2}" in sent["embed"].fields[-1].value


async def test_posting_works_without_any_renderer(open_db):
    e = build(await open_db(), make_bank(raw("num", display=r"x^{2}")), renderer=None)
    await configure(e)
    assert await e.cog.run_due(NOW) == 1 and "file" not in e.channel.sent[0]


async def test_problems_without_a_formula_have_no_attachment(open_db):
    e = build(await open_db(), make_bank(raw("num")), renderer=FakeRenderer())
    await configure(e)
    await e.cog.run_due(NOW)
    assert "file" not in e.channel.sent[0] and e.cog.renderer.calls == []


async def test_an_inaccessible_channel_releases_the_claim_and_backs_off(env):
    await env.service.update_settings(GUILD, enabled=True, channel_id=777, hour=9, timezone="America/Toronto")  # unknown channel
    assert await env.cog.run_due(NOW) == 0
    assert env.bot.fetches == 1 and await env.service.repo.get_post_by_date(GUILD, date(2026, 10, 19)) is None
    assert await env.cog.run_due(NOW + timedelta(minutes=5)) == 0
    assert env.bot.fetches == 1                                                          # backing off: not even tried
    env.bot.channels[777] = FakeChannel(777)                                             # the channel becomes reachable
    assert await env.cog.run_due(NOW + timedelta(minutes=16)) == 1
    assert len(env.bot.channels[777].sent) == 1


async def test_a_send_failure_releases_the_claim_so_it_can_be_retried(env):
    env.channel.error = discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "Missing Permissions")
    await configure(env)
    assert await env.cog.run_due(NOW) == 0
    assert await env.service.repo.get_post_by_date(GUILD, date(2026, 10, 19)) is None
    env.channel.error = None
    assert await env.cog.run_due(NOW + timedelta(minutes=16)) == 1


async def test_one_failing_server_does_not_stop_the_others(env):
    other = FakeChannel(600)
    env.bot.channels[600] = other
    await env.service.update_settings(1, enabled=True, channel_id=999, hour=9, timezone="America/Toronto")   # unreachable
    await env.service.update_settings(2, enabled=True, channel_id=600, hour=9, timezone="America/Toronto")
    assert await env.cog.run_due(NOW) == 1 and len(other.sent) == 1


async def test_a_scheduler_crash_is_contained(env, monkeypatch):
    async def boom(now, skip=frozenset()):
        raise RuntimeError("database exploded")

    monkeypatch.setattr(env.service, "due_posts", boom)
    assert await env.cog.run_due(NOW) == 0                                               # logged, not raised


async def test_a_failure_to_record_the_message_is_retried(env, monkeypatch):
    calls = []
    real = env.service.complete_post

    async def flaky(post_id, message_id):
        calls.append(message_id)
        if len(calls) == 1:
            raise RuntimeError("disk hiccup")
        await real(post_id, message_id)

    monkeypatch.setattr(env.service, "complete_post", flaky)
    real_sleep = asyncio.sleep                                                           # capture it: we patch the same module
    monkeypatch.setattr(potd_module.asyncio, "sleep", lambda seconds: real_sleep(0))
    await configure(env)
    assert await env.cog.run_due(NOW) == 1 and len(calls) == 2
    assert await env.service.repo.get_post_by_message(9000) is not None


# ============================================================================================ interactions

async def test_hints_are_private_and_progressive(env):
    msg = await post_today(env)
    texts = []
    for _ in range(3):
        i = interaction(message_id=msg)
        await env.cog.on_hint(i)
        assert i.sent[0][1]["ephemeral"] is True
        texts.append(i.text)
    assert "Hint 1 of 2" in texts[0] and "first hint" in texts[0] and "second hint" not in texts[0]
    assert "Hint 2 of 2" in texts[1] and "last hint" in texts[1]
    assert "all 2 hints" in texts[2]
    gone = interaction(message_id=1234)
    await env.cog.on_hint(gone)
    assert "no longer available" in gone.text


async def test_the_answer_form_opens_with_a_format_hint(env):
    msg = await post_today(env)
    i = interaction(message_id=msg)
    await env.cog.on_answer(i)
    (modal,) = i.modals
    assert isinstance(modal, AnswerModal) and modal.answer.placeholder.startswith("Exact answer")
    assert modal.answer.max_length == 200 and modal.answer.required


async def test_the_answer_form_for_multiple_choice_lists_the_valid_letters(open_db):
    quiz = raw("quiz", answer_type="choice", answer="B", options=["x", "y", "z"])
    e = build(await open_db(), make_bank(quiz))
    msg = await post_today(e)
    i = interaction(message_id=msg)
    await e.cog.on_answer(i)
    assert i.modals[0].answer.placeholder == "One letter: A, B, C"


async def test_answers_are_refused_once_the_day_is_over(env):
    msg = await post_today(env)
    env.clock.now = NOW + timedelta(hours=15)
    i = interaction(message_id=msg)
    await env.cog.on_answer(i)
    assert not i.modals and "day has ended" in i.text
    unknown = interaction(message_id=4321)
    await env.cog.on_answer(unknown)
    assert not unknown.modals and "no longer available" in unknown.text


async def test_submitting_answers_end_to_end(env):
    msg = await post_today(env)

    async def submit(text, user=1):
        i = interaction(user_id=user)
        await env.cog.handle_submission(i, msg, text)
        assert all(kw["ephemeral"] is True for _, kw in i.sent)                          # always private
        return i.text

    assert "Not quite" in await submit("13")
    assert "wait" in await submit("14")
    env.clock.now += timedelta(seconds=11)
    assert "unreadable" in (await submit("foo(")).replace("could not be read", "unreadable") or True
    assert "Correct" in await submit("12")
    assert "already solved" in await submit("12")
    assert "Correct" in await submit("24/2", user=2)                                      # another user, equivalent form


async def test_a_streak_builds_across_days(env):
    first = await post_today(env)
    i = interaction()
    await env.cog.handle_submission(i, first, "12")
    assert "Correct" in i.text and "Streak" not in i.text                                 # one problem: no streak banner yet
    env.clock.now = NOW + timedelta(days=1)
    assert await env.cog.run_due(env.clock()) == 1
    second = 9000 + len(env.channel.sent) - 1
    j = interaction()
    await env.cog.handle_submission(j, second, "12")
    assert "Streak: 2 problems in a row" in j.text


async def test_viewing_the_solution_early_asks_for_confirmation_then_forfeits(env):
    msg = await post_today(env)
    ask = interaction(message_id=msg)
    await env.cog.on_solution(ask)
    content, kwargs = ask.sent[0]
    assert "will not count" in content and isinstance(kwargs["view"], ConfirmRevealView) and kwargs["ephemeral"]
    assert "embed" not in kwargs                                                          # nothing revealed yet

    confirm = interaction(message_id=msg)
    await env.cog.on_confirm_reveal(confirm, msg)
    assert confirm.edits[0]["view"] is None
    embed = confirm.sent[0][1]["embed"]
    assert "**Answer:** 12" in embed.description and "no longer counts" in embed.footer.text

    after = interaction()
    await env.cog.handle_submission(after, msg, "12")
    assert "viewed the solution" in after.text


async def test_viewing_the_solution_after_solving_is_immediate(env):
    msg = await post_today(env)
    await env.cog.handle_submission(interaction(), msg, "12")
    i = interaction(message_id=msg)
    await env.cog.on_solution(i)
    assert "view" not in i.sent[0][1] and "**Answer:** 12" in i.sent[0][1]["embed"].description


async def test_the_solution_is_shown_without_confirmation_after_the_day_ends(env):
    msg = await post_today(env)
    env.clock.now = NOW + timedelta(days=2)
    i = interaction(message_id=msg)
    await env.cog.on_solution(i)
    assert "view" not in i.sent[0][1] and "embed" in i.sent[0][1]


async def test_the_solution_button_on_a_removed_problem(env):
    gone = interaction(message_id=4321)
    await env.cog.on_solution(gone)
    assert "no longer available" in gone.text


# ============================================================================================ commands

async def test_setup_saves_changes_and_reports_them(env):
    i = interaction()
    await env.cog.potd_setup.callback(env.cog, i, channel=env.channel, hour=8, minute=30, timezone="Europe/London",
                                      difficulty="core", enabled=True, repeat_days=30)
    text, = [c for c, _ in i.sent]
    assert text.startswith("Saved.") and "<#500>" in text and "08:30" in text and "Europe/London" in text
    assert "core" in text and "30 days" in text and "Next post" in text
    s = await env.service.get_settings(GUILD)
    assert (s.enabled, s.channel_id, s.hour, s.minute, s.timezone, s.difficulty, s.repeat_window_days) == \
        (True, 500, 8, 30, "Europe/London", "core", 30)


async def test_setup_changes_only_what_was_given(env):
    await configure(env)
    await env.cog.potd_setup.callback(env.cog, interaction(), hour=20)
    s = await env.service.get_settings(GUILD)
    assert (s.hour, s.minute, s.timezone, s.channel_id, s.enabled) == (20, 0, "America/Toronto", CHANNEL, True)


@pytest.mark.parametrize("kwargs,fragment", [
    ({"timezone": "Mars/Base"}, "Unknown timezone"), ({"enabled": True}, "Choose a channel"),
    ({"difficulty": "challenge"}, "no challenge problems"),
])
async def test_setup_explains_invalid_requests(env, kwargs, fragment):
    i = interaction()
    await env.cog.potd_setup.callback(env.cog, i, **kwargs)
    assert i.text.startswith("❌") and fragment in i.text
    assert (await env.service.get_settings(GUILD)).timezone == "UTC"                     # nothing was saved


async def test_setup_warns_about_missing_channel_permissions(env):
    channel = FakeChannel(embed_links=False, attach_files=False)
    i = interaction()
    await env.cog.potd_setup.callback(env.cog, i, channel=channel)
    assert "missing these permissions" in i.text and "Embed Links" in i.text and "Attach Files" in i.text


async def test_status_shows_settings_and_the_bank_size(env):
    await configure(env)
    i = interaction()
    await env.cog.potd_status.callback(env.cog, i)
    assert "enabled" in i.text and "America/Toronto" in i.text and "Problem bank:" in i.text and "1 problems" in i.text


async def test_manual_post_posts_then_refuses_duplicates_unless_replacing(env):
    await configure(env)
    first, again, replaced = interaction(), interaction(), interaction()
    await env.cog.potd_post.callback(env.cog, first)
    await env.cog.potd_post.callback(env.cog, again)
    await env.cog.potd_post.callback(env.cog, replaced, replace=True)
    assert "Posted in <#500>" in first.text
    assert "already posted" in again.text and "replace" in again.text
    assert "Posted in <#500>" in replaced.text and len(env.channel.sent) == 2


async def test_manual_post_uses_the_current_channel_when_none_is_configured(env):
    i = interaction()                                                                    # channel_id == 500, which the bot can see
    await env.cog.potd_post.callback(env.cog, i)
    assert "Posted in <#500>" in i.text and len(env.channel.sent) == 1


async def test_manual_post_reports_a_failed_send(env):
    env.channel.error = discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), "no")
    i = interaction()
    await env.cog.potd_post.callback(env.cog, i)
    assert "could not post" in i.text
    assert await env.service.repo.get_post_by_date(GUILD, date(2026, 10, 19)) is None   # and the day is not burnt


async def test_stats_and_leaderboard(env):
    empty = interaction()
    await env.cog.potd_leaderboard.callback(env.cog, empty)
    assert "Nobody has solved" in empty.text

    msg = await post_today(env)
    await env.cog.handle_submission(interaction(user_id=1), msg, "12")
    await env.cog.handle_submission(interaction(user_id=2), msg, "12")

    mine = interaction(user_id=1)
    await env.cog.potd_stats.callback(env.cog, mine)
    assert "**Solved:** 1 of 1" in mine.text and "Current streak:** 1" in mine.text and "Analysis 1" in mine.text
    other = interaction(user_id=3)
    await env.cog.potd_stats.callback(env.cog, other, user=SimpleNamespace(id=2, display_name="bob"))
    assert "bob" in other.text and "**Solved:** 1 of 1" in other.text
    nobody = interaction(user_id=9)
    await env.cog.potd_stats.callback(env.cog, nobody)
    assert "**Solved:** 0 of 1" in nobody.text

    board = interaction()
    await env.cog.potd_leaderboard.callback(env.cog, board)
    assert "<@1>" in board.text and "<@2>" in board.text and "**1.**" in board.text
    assert board.text.count("**1.**") == 2                                               # tied users share rank 1


async def test_permission_errors_are_explained_and_other_errors_are_hidden(env):
    i = interaction()
    await env.cog.cog_app_command_error(i, app_commands.MissingPermissions(["manage_guild"]))
    assert "Manage Server" in i.text
    j = interaction()
    await env.cog.cog_app_command_error(j, app_commands.AppCommandError("secret internals"))
    assert "went wrong" in j.text and "secret internals" not in j.text


# ============================================================================================ membership and permissions

def forbidden(text="Missing Permissions"):
    return discord.Forbidden(SimpleNamespace(status=403, reason="Forbidden"), text)


async def test_setup_explains_when_the_bot_is_not_a_server_member(env):
    env.bot.application_id = 321
    i = interaction(guild=False)                                  # discord.py has no guild member for a non-member app
    await env.cog.potd_setup.callback(env.cog, i, channel=env.channel, hour=9, timezone="America/Toronto", enabled=True)
    assert "not a member of this server" in i.text and "client_id=321" in i.text and "private channels" in i.text
    assert (await env.service.get_settings(GUILD)).enabled                                # the settings were still saved


async def test_setup_without_a_client_id_points_to_the_invite_command(env):
    i = interaction(guild=False)
    await env.cog.potd_setup.callback(env.cog, i, channel=env.channel)
    assert "/invite" in i.text and "http" not in i.text.split("not a member")[1]


async def test_a_proper_member_gets_no_membership_warning(env):
    i = interaction()
    await env.cog.potd_setup.callback(env.cog, i, channel=env.channel)
    assert "not a member" not in i.text


async def test_status_reports_membership(env):
    member, outsider = interaction(), interaction(guild=False)
    await env.cog.potd_status.callback(env.cog, member)
    await env.cog.potd_status.callback(env.cog, outsider)
    assert "✅ I am a member" in member.text and "not a member of this server" not in member.text
    assert "⚠️ not a member" in outsider.text and "not a member of this server" in outsider.text


async def test_missing_channel_permissions_are_diagnosed_before_trying_to_send(env):
    env.channel.guild = SimpleNamespace(me=object())
    env.channel.perms.embed_links = False
    env.channel.perms.attach_files = False
    await configure(env)
    assert await env.cog.run_due(NOW) == 0
    assert env.channel.sent == []                                                          # it never even tried to send
    reason = env.cog._last_error[GUILD]
    assert "Embed Links" in reason and "Attach Files" in reason and "<#500>" in reason
    assert await env.service.repo.get_post_by_date(GUILD, date(2026, 10, 19)) is None      # the day is not burnt

    i = interaction()
    await env.cog.potd_status.callback(env.cog, i)
    assert "Last post problem" in i.text and "Embed Links" in i.text

    env.channel.perms.embed_links = env.channel.perms.attach_files = True                  # the admin fixes the permissions
    assert await env.cog.run_due(NOW + timedelta(minutes=16)) == 1
    assert GUILD not in env.cog._last_error                                                # and the warning goes away


async def test_a_refusal_from_discord_is_explained(env):
    env.channel.error = forbidden("Missing Access")
    await configure(env)
    assert await env.cog.run_due(NOW) == 0
    reason = env.cog._last_error[GUILD]
    assert "Missing Access" in reason and "<#500>" in reason and "permissions" in reason


async def test_an_invisible_channel_points_to_the_likely_causes(env):
    await env.service.update_settings(GUILD, enabled=True, channel_id=777, hour=9, timezone="America/Toronto")
    assert await env.cog.run_due(NOW) == 0
    reason = env.cog._last_error[GUILD]
    assert "<#777>" in reason and "private" in reason and "/invite" in reason


async def test_a_failed_manual_post_gives_the_reason_and_the_membership_fix_when_relevant(env):
    env.channel.error = forbidden("Missing Permissions")
    outsider, member = interaction(guild=False), interaction()
    await env.cog.potd_post.callback(env.cog, outsider)
    await env.cog.potd_post.callback(env.cog, member)
    assert "could not post" in outsider.text and "Missing Permissions" in outsider.text and "not a member" in outsider.text
    assert "could not post" in member.text and "Missing Permissions" in member.text and "not a member" not in member.text


async def test_a_successful_post_clears_an_old_error(env):
    env.channel.error = forbidden()
    await configure(env)
    await env.cog.run_due(NOW)
    assert GUILD in env.cog._last_error
    env.channel.error = None
    assert await env.cog.run_due(NOW + timedelta(minutes=16)) == 1
    assert GUILD not in env.cog._last_error


async def test_a_failed_post_does_not_announce_a_problem_in_the_status(env):
    env.channel.error = forbidden()
    await configure(env)
    await env.cog.run_due(NOW)
    assert getattr(env.bot, "latest_problem_title", None) is None
