"""Application entry point: ``python bot.py``."""
from __future__ import annotations

import logging
import sys

import discord
from discord.ext import commands

from config import ConfigError, Settings
from database.db import Database
from math_engine.engine import MathEngine

log = logging.getLogger("mathbot")
EXTENSIONS = ("cogs.core", "cogs.calc")


class MathBot(commands.Bot):
    def __init__(self, settings: Settings) -> None:
        super().__init__(
            command_prefix=commands.when_mentioned,       # slash commands only; no message-content intent needed
            intents=discord.Intents.default(),
            allowed_mentions=discord.AllowedMentions.none(),  # echoed user text can never ping anyone
        )
        self.settings = settings
        self.engine = MathEngine(
            timeout=settings.math_timeout_seconds,
            memory_limit_mb=settings.math_memory_limit_mb,
            max_input_length=settings.math_max_input_length,
            max_concurrent=settings.math_max_concurrent,
        )
        self.db: Database | None = None

    async def setup_hook(self) -> None:
        self.db = await Database.open(self.settings.database_path)
        for ext in EXTENSIONS:
            await self.load_extension(ext)
        if self.settings.dev_guild_id:
            guild = discord.Object(id=self.settings.dev_guild_id)
            self.tree.copy_global_to(guild=guild)
            synced = await self.tree.sync(guild=guild)
            log.info("Synced %d commands to dev guild %s", len(synced), self.settings.dev_guild_id)
        else:
            synced = await self.tree.sync()
            log.info("Synced %d global commands (may take a while to appear)", len(synced))

    async def on_ready(self) -> None:
        log.info("Logged in as %s (id=%s)", self.user, getattr(self.user, "id", "?"))

    async def close(self) -> None:
        if self.db:
            await self.db.close()
        await super().close()


def main() -> None:
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    try:
        settings = Settings.from_env()
    except ConfigError as exc:
        sys.exit(f"Configuration error: {exc}")
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)-8s %(name)s: %(message)s")
    MathBot(settings).run(settings.discord_token, log_handler=None)  # we configured logging ourselves


if __name__ == "__main__":
    main()
