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
        )
