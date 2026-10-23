"""The real MathBot wiring, without a network connection: every extension loads, and every slash command serialises
into the payload Discord's API would receive (this is where over-long descriptions or bad option order would fail)."""
from pathlib import Path

import pytest

from bot import EXTENSIONS, MathBot
from config import Settings
from services.problem_bank import load_bank

BANK_PATH = Path(__file__).resolve().parent.parent / "data" / "problems.yaml"


@pytest.fixture
async def bot(tmp_path, monkeypatch):
    settings = Settings.from_env({"DISCORD_TOKEN": "not-a-real-token", "DATABASE_PATH": str(tmp_path / "bot.sqlite3"),
                                  "DEV_GUILD_ID": "123"})
    instance = MathBot(settings, load_bank(BANK_PATH))
    await instance._async_setup_hook()

    synced = []

    async def fake_sync(*, guild=None):
        synced.append(guild)
        return []

    monkeypatch.setattr(instance.tree, "sync", fake_sync)
    await instance.setup_hook()
    instance.synced = synced
    yield instance
    await instance.close()


async def test_every_extension_loads_and_the_expected_commands_exist(bot):
    assert set(bot.extensions) == set(EXTENSIONS)
    names = {c.name for c in bot.tree.get_commands()}
    assert names == {"ping", "invite", "simplify", "factor", "expand", "diff", "integrate", "limit", "evaluate", "solve",
                     "matrix", "latex", "potd"}
    assert {c.name for c in bot.tree.get_command("potd").commands} == {"setup", "status", "post", "stats", "leaderboard"}
    assert len(bot.synced) == 1                                       # synced once, to the dev guild


async def test_every_command_serialises_into_a_valid_api_payload(bot):
    payloads = [c.to_dict(bot.tree) for c in bot.tree.get_commands()]
    assert len(payloads) < 100                                         # Discord's limit on global commands
    for payload in payloads:
        assert 1 <= len(payload["name"]) <= 32 and 1 <= len(payload["description"]) <= 100, payload["name"]
        stack = list(payload.get("options", []))
        while stack:
            option = stack.pop()
            assert 1 <= len(option["name"]) <= 32 and 1 <= len(option["description"]) <= 100, option["name"]
            for choice in option.get("choices", []):
                assert 1 <= len(choice["name"]) <= 100
            stack.extend(option.get("options", []))                    # subcommands


async def test_required_options_come_before_optional_ones(bot):
    """Discord rejects a command whose required options follow optional ones."""
    def check(options):
        seen_optional = False
        for option in options:
            if option.get("type") in (1, 2):                           # a subcommand / group: recurse
                check(option.get("options", []))
                continue
            assert not (seen_optional and option.get("required")), option["name"]
            seen_optional = seen_optional or not option.get("required")

    for command in bot.tree.get_commands():
        check(command.to_dict(bot.tree).get("options", []))


async def test_startup_wires_the_potd_service_to_the_database_and_bank(bot):
    assert bot.potd_service.bank is bot.bank and len(bot.bank) >= 40
    assert (await bot.potd_service.get_settings(1)).enabled is False   # the migration ran: the table exists and is usable


async def test_the_scheduler_loop_is_running_after_startup(bot):
    assert bot.get_cog("Potd").tick.is_running()


def test_a_broken_problem_file_stops_the_bot_at_startup_with_a_readable_message(tmp_path, monkeypatch):
    import bot as bot_module
    broken = tmp_path / "problems.yaml"
    broken.write_text("problems:\n  - id: Not_A_Slug\n    subject: alchemy\n", encoding="utf-8")
    monkeypatch.setenv("DISCORD_TOKEN", "not-a-real-token")
    monkeypatch.setenv("PROBLEMS_PATH", str(broken))
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)         # do not read a developer's real .env
    with pytest.raises(SystemExit) as info:
        bot_module.main()
    message = str(info.value)
    assert "Problem bank has errors" in message and "Not_A_Slug" in message and "Traceback" not in message


def test_a_missing_token_stops_the_bot_with_a_readable_message(monkeypatch):
    import bot as bot_module
    monkeypatch.delenv("DISCORD_TOKEN", raising=False)
    monkeypatch.setattr("dotenv.load_dotenv", lambda *a, **k: None)
    with pytest.raises(SystemExit) as info:
        bot_module.main()
    assert "DISCORD_TOKEN" in str(info.value)


def make_settings(tmp_path, **env):
    return Settings.from_env({"DISCORD_TOKEN": "not-a-real-token", "DATABASE_PATH": str(tmp_path / "s.sqlite3"), **env})


async def test_the_bot_logs_in_online_with_a_playing_activity(tmp_path):
    import discord
    instance = MathBot(make_settings(tmp_path), load_bank(BANK_PATH))
    assert instance.status is discord.Status.online
    assert instance.activity.type is discord.ActivityType.playing and instance.activity.name.startswith("Problem bank: ")
    await instance.close()


@pytest.mark.parametrize("value,expected", [("idle", "idle"), ("dnd", "dnd"), ("invisible", "invisible")])
async def test_the_configured_status_is_used(tmp_path, value, expected):
    instance = MathBot(make_settings(tmp_path, BOT_STATUS=value), load_bank(BANK_PATH))
    assert instance.status.value == expected
    await instance.close()


async def test_presence_can_be_switched_off(tmp_path):
    instance = MathBot(make_settings(tmp_path, PRESENCE_ENABLED="false"), load_bank(BANK_PATH))
    assert instance.activity is None
    await instance.close()


async def test_the_presence_rotation_starts_with_the_bot(bot):
    assert bot.get_cog("Presence").tick.is_running()
    assert bot.get_cog("Presence").tick.minutes == 10
