"""The bot's online status and rotating activity.

How Discord shows it: in the member list a *Playing* activity appears as bare text with no "Playing" in front, while
Watching / Listening to / Competing in keep their prefix, and the list is narrow, so long text is cut off. So every
"playing" line is written like a game title, every other line is written to follow its prefix (never repeating it),
and the key words come first.

Bots can set an activity type and its text. Discord's richer "Rich Presence" (timestamps, buttons, images) is not
available to bots. As an option (PRESENCE_STYLE=custom) the same lines are sent as a *custom status* (an emoji plus
free text, no prefix), which Discord may or may not display for bots; the default typed activities are known to work.
"""
from __future__ import annotations

import logging
import random
from dataclasses import dataclass

import discord
from discord.ext import commands, tasks

log = logging.getLogger(__name__)

MAX_ACTIVITY_CHARS = 100   # Discord allows 128; stay comfortably below
SIDEBAR_CHARS = 36         # the member list cuts text off; static lines must stay within this
STYLES = ("activity", "custom")


@dataclass(frozen=True)
class PresenceLine:
    kind: str    # playing | watching | listening | competing
    text: str    # may use {servers}, {servers_s}, {problems} and {title}


STARTUP = PresenceLine("playing", "Problem bank: {problems} problems")

LINES: tuple[PresenceLine, ...] = (
    # Playing: shown without a prefix, so these read like game titles.
    PresenceLine("playing", "Nim (XOR the piles)"),
    PresenceLine("playing", "Hanoi, 10 discs: 1,023 moves"),
    PresenceLine("playing", "Collatz: 27 → 111 steps"),
    PresenceLine("playing", "Hide and seek with i"),
    PresenceLine("playing", "Möbius strip (one side)"),
    PresenceLine("playing", "Banach–Tarski (1 ball → 2)"),
    PresenceLine("playing", "Taxicab: 1729 = 9³ + 10³"),
    PresenceLine("playing", "Euler: e^(iπ) + 1 = 0"),
    PresenceLine("playing", "Sudoku (6.67 × 10²¹ grids)"),
    PresenceLine("playing", "Dice: law of large numbers"),
    PresenceLine("playing", "Dominoes (induction)"),
    PresenceLine("playing", "Fibonacci spiral"),
    PresenceLine("playing", "/solve /integrate /matrix"),
    PresenceLine("playing", "Problem bank: {problems} problems"),
    PresenceLine("playing", "Today: {title}"),                 # only used once a problem has been posted
    # Watching / Listening to / Competing in: Discord adds the words, so none of these repeat them.
    PresenceLine("watching", "the primes thin out"),
    PresenceLine("watching", "over {servers} server{servers_s}"),
    PresenceLine("watching", "√2 never end"),
    PresenceLine("watching", "the zeta zeros line up"),
    PresenceLine("watching", "a 1D random walk return"),
    PresenceLine("watching", "a geometric series converge"),
    PresenceLine("listening", "the harmonic series"),
    PresenceLine("listening", "the spheres' music"),
    PresenceLine("listening", "a pure sine wave"),
    PresenceLine("competing", "an unofficial Putnam"),
    PresenceLine("competing", "a race to infinity"),
)

_TYPES = {
    "watching": discord.ActivityType.watching,
    "listening": discord.ActivityType.listening,
    "competing": discord.ActivityType.competing,
}
_PREFIX = {"playing": "Playing", "watching": "Watching", "listening": "Listening to", "competing": "Competing in"}
_EMOJI = {"playing": "🎮", "watching": "👀", "listening": "🎧", "competing": "🏆"}


def context_for(servers: int, problems: int, title: str | None = None) -> dict:
    return {"servers": servers, "servers_s": "" if servers == 1 else "s", "problems": problems, "title": title or ""}


def available(line: PresenceLine, context: dict) -> bool:
    """A line that shows today's problem needs one to exist."""
    return "{title}" not in line.text or bool(context.get("title"))


def render(line: PresenceLine, context: dict) -> str:
    return line.text.format(**context)[:MAX_ACTIVITY_CHARS]


def build_activity(line: PresenceLine, context: dict, style: str = "activity") -> discord.BaseActivity:
    name = render(line, context)
    if style == "custom":      # a custom status: emoji + free text, so the words Discord would add are included here
        return discord.CustomActivity(name=f"{_PREFIX[line.kind]} {name}"[:MAX_ACTIVITY_CHARS], emoji=_EMOJI[line.kind])
    if line.kind == "playing":
        return discord.Game(name=name)
    return discord.Activity(type=_TYPES[line.kind], name=name)


def initial_activity(settings, problem_count: int) -> discord.BaseActivity | None:
    """The activity sent with the login, so the bot never appears blank. None if presence is switched off."""
    if not settings.presence_enabled:
        return None
    return build_activity(STARTUP, context_for(0, problem_count), settings.presence_style)


class Presence(commands.Cog):
    def __init__(self, bot: commands.Bot, settings, rng: random.Random | None = None) -> None:
        self.bot, self.settings = bot, settings
        self.rng = rng or random.Random()
        self._queue: list[PresenceLine] = []
        self._last: PresenceLine | None = None

    async def cog_load(self) -> None:
        if self.settings.presence_enabled:
            self.tick.change_interval(minutes=self.settings.presence_interval_minutes)
            self.tick.start()

    async def cog_unload(self) -> None:
        self.tick.cancel()

    def context(self) -> dict:
        return context_for(len(self.bot.guilds), len(getattr(self.bot, "bank", ())),
                           getattr(self.bot, "latest_problem_title", None))

    def next_line(self, context: dict | None = None) -> PresenceLine:
        """Shuffled round-robin: every usable line is shown once per cycle, and never twice in a row."""
        context = context if context is not None else self.context()
        if not any(line in self._queue and available(line, context) for line in self._queue):
            self._queue = [line for line in LINES if available(line, context)]
            self.rng.shuffle(self._queue)
            if len(self._queue) > 1 and self._queue[-1] == self._last:
                self._queue[0], self._queue[-1] = self._queue[-1], self._queue[0]
        while not available(self._queue[-1], context):          # the problem title is not known (yet): skip that line
            self._queue.pop()
        self._last = self._queue.pop()
        return self._last

    async def apply(self) -> None:
        """Show the next activity. Never raises: a failed presence update must not matter to anything else."""
        try:
            context = self.context()
            await self.bot.change_presence(
                status=discord.Status(self.settings.bot_status),
                activity=build_activity(self.next_line(context), context, self.settings.presence_style))
        except Exception:  # noqa: BLE001
            log.exception("Could not update the bot's presence")

    @tasks.loop(minutes=10)
    async def tick(self) -> None:
        if self.tick.current_loop == 0:
            return                       # the login already set an activity; start rotating on the next beat
        await self.apply()

    @tick.before_loop
    async def _before_tick(self) -> None:
        await self.bot.wait_until_ready()


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Presence(bot, bot.settings))  # type: ignore[attr-defined]
