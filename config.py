"""Configuration, read from environment variables (optionally via a local .env file)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Mapping


class ConfigError(Exception):
    """Raised when required configuration is missing or invalid."""


def _number(env: Mapping[str, str], name: str, default, cast, minimum):
    raw = env.get(name)
    if raw in (None, ""):
        return default
    try:
        value = cast(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number, got {raw!r}.") from None
    if value < minimum:
        raise ConfigError(f"{name} must be at least {minimum}, got {value}.")
    return value


def _boolean(env: Mapping[str, str], name: str, default: bool) -> bool:
    raw = (env.get(name) or "").strip().lower()
    if not raw:
        return default
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    raise ConfigError(f"{name} must be true or false, got {raw!r}.")


BOT_STATUSES = ("online", "idle", "dnd", "invisible")


@dataclass(frozen=True)
class Settings:
    discord_token: str = field(repr=False)   # repr=False so the token never appears in logs
    database_path: str = "data/mathbot.sqlite3"
    log_level: str = "INFO"
    dev_guild_id: int | None = None          # if set, commands sync to this server instantly
    math_timeout_seconds: float = 15.0
    math_memory_limit_mb: int = 512
    math_max_input_length: int = 200
    math_max_concurrent: int = 2
    latex_max_length: int = 300
    problems_path: str = "data/problems.yaml"
    bot_status: str = "online"             # online | idle | dnd | invisible
    presence_enabled: bool = True          # show a rotating "Playing ..." activity
    presence_interval_minutes: int = 10
    presence_style: str = "activity"       # activity (Playing/Watching/...) | custom (emoji + text status)

    @staticmethod
    def _status(env: Mapping[str, str]) -> str:
        value = (env.get("BOT_STATUS") or "online").strip().lower()
        if value not in BOT_STATUSES:
            raise ConfigError(f"BOT_STATUS must be one of {', '.join(BOT_STATUSES)}, got {value!r}.")
        return value

    @staticmethod
    def _style(env: Mapping[str, str]) -> str:
        value = (env.get("PRESENCE_STYLE") or "activity").strip().lower()
        if value not in ("activity", "custom"):
            raise ConfigError(f"PRESENCE_STYLE must be 'activity' or 'custom', got {value!r}.")
        return value

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "Settings":
        env = os.environ if env is None else env
        token = (env.get("DISCORD_TOKEN") or "").strip()
        if not token:
            raise ConfigError("DISCORD_TOKEN is not set. Copy .env.example to .env and fill it in.")
        guild = env.get("DEV_GUILD_ID")
        return cls(
            discord_token=token,
            database_path=env.get("DATABASE_PATH") or cls.database_path,
            log_level=(env.get("LOG_LEVEL") or cls.log_level).upper(),
            dev_guild_id=_number(env, "DEV_GUILD_ID", None, int, 1) if guild else None,
            math_timeout_seconds=_number(env, "MATH_TIMEOUT_SECONDS", cls.math_timeout_seconds, float, 1),
            math_memory_limit_mb=_number(env, "MATH_MEMORY_LIMIT_MB", cls.math_memory_limit_mb, int, 64),
            math_max_input_length=_number(env, "MATH_MAX_INPUT_LENGTH", cls.math_max_input_length, int, 10),
            math_max_concurrent=_number(env, "MATH_MAX_CONCURRENT", cls.math_max_concurrent, int, 1),
            latex_max_length=_number(env, "LATEX_MAX_LENGTH", cls.latex_max_length, int, 20),
            problems_path=env.get("PROBLEMS_PATH") or cls.problems_path,
            bot_status=cls._status(env),
            presence_enabled=_boolean(env, "PRESENCE_ENABLED", cls.presence_enabled),
            presence_interval_minutes=_number(env, "PRESENCE_INTERVAL_MINUTES", cls.presence_interval_minutes, int, 1),
            presence_style=cls._style(env),
        )
