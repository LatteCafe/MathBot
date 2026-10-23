import cmath
import math
import random
from functools import lru_cache
from itertools import product
from types import SimpleNamespace

import discord
import pytest

from cogs.presence import (LINES, MAX_ACTIVITY_CHARS, SIDEBAR_CHARS, STARTUP, Presence, available, build_activity,
                           context_for, initial_activity, render)
from config import ConfigError, Settings

VISIBLE_PREFIX = {"playing": "", "watching": "Watching ", "listening": "Listening to ", "competing": "Competing in "}
NO_TITLE = context_for(3, 42)
WITH_TITLE = context_for(3, 42, "Zeros in an annulus")


def settings(**env):
    return Settings.from_env({"DISCORD_TOKEN": "x", **env})


class FakeBot:
    def __init__(self, guilds=3, problems=42, title=None):
        self.guilds, self.bank, self.calls, self.error = list(range(guilds)), list(range(problems)), [], None
        if title:
            self.latest_problem_title = title

    async def change_presence(self, *, status, activity):
        if self.error:
            raise self.error
        self.calls.append((status, activity))

    async def wait_until_ready(self):
        pass


def usable(context=NO_TITLE):
    return [line for line in LINES if available(line, context)]


# ------------------------------------------------------------------------------------------ how the lines look

def test_the_lines_are_valid_varied_and_within_discords_limits():
    assert len(LINES) >= 20 and len(set(LINES)) == len(LINES)
    assert {line.kind for line in LINES} == {"playing", "watching", "listening", "competing"}
    for servers in (0, 1, 2, 500):
        for line in LINES + (STARTUP,):
            text = render(line, context_for(servers, 42, "A title"))
            assert 1 <= len(text) <= MAX_ACTIVITY_CHARS < 128, text
            assert "{" not in text and "}" not in text, text


def test_every_line_fits_in_the_narrow_member_list_prefix_included():
    """The member list cuts text off, so what is VISIBLE (Discord's prefix plus our text) must stay short."""
    for line in LINES:
        if "{title}" in line.text:
            continue                                   # a problem title can be long; its key words come first
        visible = VISIBLE_PREFIX[line.kind] + render(line, context_for(10, 100))
        assert len(visible) <= SIDEBAR_CHARS, f"{visible!r} is {len(visible)} characters"


def test_lines_never_repeat_the_words_discord_adds():
    """Regression: 'competing' lines used to start with 'in', giving 'Competing in in the Putnam'."""
    for line in LINES:
        text = line.text.lower()
        if line.kind == "competing":
            assert not text.startswith(("in ", "competing")), line.text
        if line.kind == "listening":
            assert not text.startswith(("to ", "listening")), line.text
        if line.kind == "watching":
            assert not text.startswith("watching"), line.text


def test_playing_lines_read_like_titles_because_discord_shows_them_without_a_prefix():
    """Regression: 'with 42 math problems' looked like a sentence fragment in the member list."""
    for line in LINES + (STARTUP,):
        if line.kind == "playing":
            text = render(line, WITH_TITLE)
            assert text[0].isupper() or text[0] == "/", text
            assert not text.lower().startswith(("with ", "playing ", "a ", "the ")), text


def test_plurals_follow_the_server_count():
    line = next(l for l in LINES if "{servers}" in l.text)
    assert render(line, context_for(1, 1)) == "over 1 server"
    assert render(line, context_for(7, 1)) == "over 7 servers"
    assert render(line, context_for(0, 1)) == "over 0 servers"


# ------------------------------------------------------------------------------------------ the facts in the lines

@lru_cache(maxsize=None)
def nim_position_is_lost(piles: tuple) -> bool:
    """Brute force: the player to move loses if every move leads to a winning position for the opponent."""
    piles = tuple(sorted(piles))
    if not any(piles):
        return True
    for i, n in enumerate(piles):
        for take in range(1, n + 1):
            moved = piles[:i] + (n - take,) + piles[i + 1:]
            if nim_position_is_lost(tuple(sorted(moved))):
                return False
    return True


def test_the_trivia_in_the_status_lines_is_actually_true():
    """A maths bot should not get its own jokes wrong."""
    def collatz_steps(n):
        steps = 0
        while n != 1:
            n, steps = (n // 2 if n % 2 == 0 else 3 * n + 1), steps + 1
        return steps

    text = " | ".join(l.text for l in LINES)
    assert collatz_steps(27) == 111 and "27 → 111 steps" in text
    assert 1**3 + 12**3 == 9**3 + 10**3 == 1729 and "1729 = 9³ + 10³" in text
    assert 2**10 - 1 == 1023 and "10 discs: 1,023 moves" in text
    assert abs(cmath.exp(1j * math.pi) + 1) < 1e-15 and "e^(iπ) + 1 = 0" in text
    sudoku_grids = 6_670_903_752_021_072_936_960                                   # Felgenhauer & Jarvis (2005)
    assert f"{sudoku_grids / 1e21:.2f}" == "6.67" and "6.67 × 10²¹ grids" in text
    # "√2 never end": a terminating decimal is a/10^k, so sqrt(2) = a/10^k would need 2*10^(2k) to be a perfect square.
    assert all(math.isqrt(2 * 10 ** (2 * k)) ** 2 != 2 * 10 ** (2 * k) for k in range(300)) and "√2 never end" in text


def test_nim_is_lost_exactly_when_the_xor_of_the_piles_is_zero():
    """The claim in 'Nim (XOR the piles)', checked by exhaustive search over every position with piles up to 5."""
    for piles in product(range(6), repeat=3):
        assert nim_position_is_lost(tuple(sorted(piles))) == (piles[0] ^ piles[1] ^ piles[2] == 0), piles
    assert any(line.text == "Nim (XOR the piles)" for line in LINES)            # and the line says exactly that


# ------------------------------------------------------------------------------------------ building activities

def test_activity_objects_have_the_right_types():
    playing = build_activity(next(l for l in LINES if l.kind == "playing"), NO_TITLE)
    assert isinstance(playing, discord.Game) and playing.type is discord.ActivityType.playing
    for kind, expected in [("watching", discord.ActivityType.watching), ("listening", discord.ActivityType.listening),
                           ("competing", discord.ActivityType.competing)]:
        activity = build_activity(next(l for l in LINES if l.kind == kind), NO_TITLE)
        assert isinstance(activity, discord.Activity) and activity.type is expected and activity.name


@pytest.mark.parametrize("kind,prefix,emoji", [("playing", "Playing", "🎮"), ("watching", "Watching", "👀"),
                                               ("listening", "Listening to", "🎧"), ("competing", "Competing in", "🏆")])
def test_custom_style_spells_out_the_words_discord_would_have_added(kind, prefix, emoji):
    line = next(l for l in LINES if l.kind == kind)
    activity = build_activity(line, NO_TITLE, "custom")
    assert isinstance(activity, discord.CustomActivity)
    assert activity.name == f"{prefix} {render(line, NO_TITLE)}" and str(activity.emoji) == emoji


def test_the_login_activity_respects_the_off_switch_and_the_style():
    assert initial_activity(settings(), 42).name == "Problem bank: 42 problems"
    assert isinstance(initial_activity(settings(), 42), discord.Game)
    assert initial_activity(settings(PRESENCE_ENABLED="false"), 42) is None
    custom = initial_activity(settings(PRESENCE_STYLE="custom"), 42)
    assert isinstance(custom, discord.CustomActivity) and custom.name == "Playing Problem bank: 42 problems"


# ------------------------------------------------------------------------------------------ rotation

def test_every_usable_line_is_shown_once_per_cycle_and_never_twice_in_a_row():
    cog = Presence(FakeBot(), settings(), random.Random(1))
    expected = sorted(usable(), key=lambda l: l.text)
    shown = [cog.next_line() for _ in range(len(expected) * 6)]
    for start in range(0, len(shown), len(expected)):
        assert sorted(shown[start:start + len(expected)], key=lambda l: l.text) == expected
    assert all(a != b for a, b in zip(shown, shown[1:]))


def test_the_todays_problem_line_appears_only_once_a_problem_has_been_posted():
    without = Presence(FakeBot(), settings(), random.Random(2))
    assert not any("{title}" in without.next_line().text for _ in range(200))
    with_title = Presence(FakeBot(title="Zeros in an annulus"), settings(), random.Random(2))
    assert any("{title}" in with_title.next_line().text for _ in range(len(LINES)))


def test_rotation_is_reproducible_with_a_seed_and_varies_without():
    a, b = Presence(FakeBot(), settings(), random.Random(7)), Presence(FakeBot(), settings(), random.Random(7))
    assert [a.next_line() for _ in range(30)] == [b.next_line() for _ in range(30)]
    c = Presence(FakeBot(), settings(), random.Random(8))
    assert [c.next_line() for _ in range(30)] != [Presence(FakeBot(), settings(), random.Random(7)).next_line() for _ in range(30)]


@pytest.mark.parametrize("seed", range(40))
def test_the_boundary_between_two_cycles_never_repeats_a_line(seed):
    """Force the worst case: the line just shown is the one the next shuffle would show first."""
    cog = Presence(FakeBot(), settings(), random.Random(seed))
    peek = random.Random(seed)
    upcoming = usable()
    peek.shuffle(upcoming)                       # exactly the shuffle next_line is about to perform
    cog._last = upcoming[-1]                     # ... and upcoming[-1] is what it would pop first
    assert cog.next_line() != upcoming[-1]


# ------------------------------------------------------------------------------------------ applying it

async def test_apply_sets_the_configured_status_and_a_live_activity():
    bot = FakeBot(guilds=1, problems=42, title="Zeros in an annulus")
    cog = Presence(bot, settings(BOT_STATUS="idle"), random.Random(3))
    for _ in range(len(LINES)):
        await cog.apply()
    assert {status for status, _ in bot.calls} == {discord.Status.idle}
    names = [activity.name for _, activity in bot.calls]
    assert "over 1 server" in names and "Problem bank: 42 problems" in names and "Today: Zeros in an annulus" in names


async def test_the_custom_style_is_used_when_configured():
    bot = FakeBot()
    await Presence(bot, settings(PRESENCE_STYLE="custom"), random.Random(3)).apply()
    assert isinstance(bot.calls[0][1], discord.CustomActivity)


async def test_a_failed_presence_update_never_raises():
    bot = FakeBot()
    bot.error = discord.HTTPException(SimpleNamespace(status=500, reason="boom"), "boom")
    await Presence(bot, settings()).apply()                                        # logged, not raised
    bot.error = ConnectionResetError("socket closed")
    await Presence(bot, settings()).apply()


async def test_the_loop_skips_its_first_beat_because_login_already_set_an_activity():
    bot = FakeBot()
    cog = Presence(bot, settings())
    await cog.tick.coro(cog)                                    # current_loop == 0
    assert bot.calls == []
    cog.tick._current_loop = 1
    await cog.tick.coro(cog)
    assert len(bot.calls) == 1


async def test_loading_starts_the_rotation_with_the_configured_interval():
    cog = Presence(FakeBot(), settings(PRESENCE_INTERVAL_MINUTES="3"))
    await cog.cog_load()
    try:
        assert cog.tick.is_running() and cog.tick.minutes == 3
    finally:
        await cog.cog_unload()


async def test_loading_with_presence_disabled_starts_nothing():
    cog = Presence(FakeBot(), settings(PRESENCE_ENABLED="false"))
    await cog.cog_load()
    assert not cog.tick.is_running()
    await cog.cog_unload()


# ------------------------------------------------------------------------------------------ configuration

def test_presence_defaults():
    s = settings()
    assert (s.bot_status, s.presence_enabled, s.presence_interval_minutes, s.presence_style) == ("online", True, 10, "activity")


@pytest.mark.parametrize("value,expected", [("online", "online"), ("IDLE", "idle"), (" dnd ", "dnd"), ("invisible", "invisible")])
def test_status_values(value, expected):
    assert settings(BOT_STATUS=value).bot_status == expected


@pytest.mark.parametrize("env", [{"BOT_STATUS": "away"}, {"PRESENCE_ENABLED": "maybe"}, {"PRESENCE_INTERVAL_MINUTES": "0"},
                                 {"PRESENCE_INTERVAL_MINUTES": "soon"}, {"PRESENCE_STYLE": "fancy"}])
def test_invalid_presence_settings_are_rejected(env):
    with pytest.raises(ConfigError):
        settings(**env)


@pytest.mark.parametrize("value,expected", [("activity", "activity"), (" CUSTOM ", "custom")])
def test_presence_style_values(value, expected):
    assert settings(PRESENCE_STYLE=value).presence_style == expected


@pytest.mark.parametrize("value,expected", [("true", True), ("1", True), ("YES", True), ("on", True),
                                            ("false", False), ("0", False), ("no", False), ("OFF", False)])
def test_presence_enabled_accepts_common_spellings(value, expected):
    assert settings(PRESENCE_ENABLED=value).presence_enabled is expected
