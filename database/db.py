"""SQLite connection and versioned migrations.

Migrations are plain SQL files in database/migrations/, named ``NNN_description.sql``. Each runs once,
in order, and is recorded in ``schema_migrations``. To change the schema, add a NEW file; never edit
one that has already been applied.
"""
from __future__ import annotations

import logging
from pathlib import Path

import aiosqlite

log = logging.getLogger(__name__)
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


class Database:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self.conn = conn

    @classmethod
    async def open(cls, path: str) -> "Database":
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        conn = await aiosqlite.connect(path)
        conn.row_factory = aiosqlite.Row
        await conn.execute("PRAGMA journal_mode=WAL")
        await conn.execute("PRAGMA foreign_keys=ON")
        db = cls(conn)
        await db.migrate()
        return db

    async def migrate(self) -> list[int]:
        """Apply any pending migrations. Returns the versions applied in this call."""
        await self.conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        await self.conn.commit()
        async with self.conn.execute("SELECT version FROM schema_migrations") as cur:
            done = {row["version"] for row in await cur.fetchall()}

        applied = []
        for file in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = int(file.name.split("_", 1)[0])
            if version in done:
                continue
            name = file.stem.replace("'", "")
            # One script so the schema change and its bookkeeping row commit (or roll back) together.
            await self.conn.executescript(
                f"BEGIN;\n{file.read_text()}\n"
                f"INSERT INTO schema_migrations (version, name) VALUES ({version}, '{name}');\nCOMMIT;"
            )
            log.info("Applied database migration %s", file.name)
            applied.append(version)
        return applied

    async def close(self) -> None:
        await self.conn.close()
