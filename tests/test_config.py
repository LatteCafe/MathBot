import pytest

from config import ConfigError, Settings


def test_missing_token_is_an_error():
    with pytest.raises(ConfigError, match="DISCORD_TOKEN"):
        Settings.from_env({})
    with pytest.raises(ConfigError):
        Settings.from_env({"DISCORD_TOKEN": "   "})


def test_defaults():
    s = Settings.from_env({"DISCORD_TOKEN": "abc"})
    assert s.database_path == "data/mathbot.sqlite3"
    assert s.math_timeout_seconds == 15.0 and s.dev_guild_id is None


def test_overrides_and_parsing():
    s = Settings.from_env({"DISCORD_TOKEN": "abc", "DEV_GUILD_ID": "123", "MATH_TIMEOUT_SECONDS": "5",
                           "LOG_LEVEL": "debug"})
    assert s.dev_guild_id == 123 and s.math_timeout_seconds == 5.0 and s.log_level == "DEBUG"


@pytest.mark.parametrize("env", [{"MATH_TIMEOUT_SECONDS": "fast"}, {"MATH_TIMEOUT_SECONDS": "0"},
                                 {"MATH_MEMORY_LIMIT_MB": "1"}, {"DEV_GUILD_ID": "abc"}])
def test_invalid_numbers_are_rejected(env):
    with pytest.raises(ConfigError):
        Settings.from_env({"DISCORD_TOKEN": "abc", **env})


def test_token_never_appears_in_repr():
    assert "secret-token" not in repr(Settings.from_env({"DISCORD_TOKEN": "secret-token"}))
