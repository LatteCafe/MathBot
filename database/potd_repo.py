"""SQL for Problem of the Day. All timestamps are stored as UTC text in one fixed-width format."""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .db import Database

_FORMAT = "%Y-%m-%d %H:%M:%S.%f"
DIFFICULTIES = ("any", "core", "advanced", "challenge")


def to_db(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime(_FORMAT)


def from_db(text: str | None) -> datetime | None:
    return datetime.strptime(text, _FORMAT).replace(tzinfo=timezone.utc) if text else None


@dataclass(frozen=True)
class GuildSettings:
    guild_id: int
    enabled: bool = False
    channel_id: int | None = None
    hour: int = 9
    minute: int = 0
    timezone: str = "UTC"
    difficulty: str = "any"
    repeat_window_days: int = 60

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    def with_changes(self, **changes) -> "GuildSettings":
        return replace(self, **changes)


@dataclass(frozen=True)
class Post:
    id: int
    guild_id: int
    problem_id: str
    post_date: date
    timezone: str
    channel_id: int | None
    message_id: int | None
    claimed_at: datetime


@dataclass(frozen=True)
class Progress:
    hints_used: int = 0
    attempts: int = 0
    last_attempt_at: datetime | None = None
    solved_at: datetime | None = None
    revealed_at: datetime | None = None


def _post(row) -> Post:
    return Post(row["id"], row["guild_id"], row["problem_id"], date.fromisoformat(row["post_date"]), row["timezone"],
                row["channel_id"], row["message_id"], from_db(row["claimed_at"]))


class PotdRepository:
    def __init__(self, db: Database) -> None:
        self.conn = db.conn

    async def _one(self, sql: str, params: tuple = ()):
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchone()

    async def _all(self, sql: str, params: tuple = ()):
        async with self.conn.execute(sql, params) as cur:
            return await cur.fetchall()

    # ------------------------------------------------------------------------------------------- settings

    async def get_settings(self, guild_id: int) -> GuildSettings:
        row = await self._one("SELECT * FROM guild_settings WHERE guild_id = ?", (guild_id,))
        return self._settings(row) if row else GuildSettings(guild_id)

    @staticmethod
    def _settings(row) -> GuildSettings:
        return GuildSettings(row["guild_id"], bool(row["potd_enabled"]), row["potd_channel_id"], row["potd_hour"],
                             row["potd_minute"], row["timezone"], row["difficulty"], row["repeat_window_days"])

    async def save_settings(self, s: GuildSettings) -> None:
        await self.conn.execute(
            """INSERT INTO guild_settings (guild_id, potd_enabled, potd_channel_id, potd_hour, potd_minute, timezone,
                                           difficulty, repeat_window_days)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT (guild_id) DO UPDATE SET potd_enabled = excluded.potd_enabled,
                 potd_channel_id = excluded.potd_channel_id, potd_hour = excluded.potd_hour,
                 potd_minute = excluded.potd_minute, timezone = excluded.timezone, difficulty = excluded.difficulty,
                 repeat_window_days = excluded.repeat_window_days""",
            (s.guild_id, int(s.enabled), s.channel_id, s.hour, s.minute, s.timezone, s.difficulty, s.repeat_window_days))
        await self.conn.commit()

    async def enabled_guilds(self) -> list[GuildSettings]:
        rows = await self._all("SELECT * FROM guild_settings WHERE potd_enabled = 1 AND potd_channel_id IS NOT NULL")
        return [self._settings(r) for r in rows]

    # ------------------------------------------------------------------------------------------- posts

    async def get_post_by_date(self, guild_id: int, day: date) -> Post | None:
        row = await self._one("SELECT * FROM potd_posts WHERE guild_id = ? AND post_date = ?", (guild_id, day.isoformat()))
        return _post(row) if row else None

    async def get_post_by_message(self, message_id: int) -> Post | None:
        row = await self._one("SELECT * FROM potd_posts WHERE message_id = ?", (message_id,))
        return _post(row) if row else None

    async def claim_post(self, guild_id: int, day: date, problem_id: str, channel_id: int | None, tz_name: str,
                         now: datetime, stale_after: timedelta) -> Post | None:
        """Reserve (guild, day). Returns the new Post, or None if that day already has a post.

        A claim whose Discord message was never sent (the bot crashed between claiming and sending) is taken over
        once it is older than `stale_after`, so a crash causes a delayed post, never a missing one or a duplicate.
        """
        cur = await self.conn.execute(
            """INSERT INTO potd_posts (guild_id, problem_id, post_date, timezone, channel_id, claimed_at)
               VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (guild_id, post_date) DO NOTHING""",
            (guild_id, problem_id, day.isoformat(), tz_name, channel_id, to_db(now)))
        if cur.rowcount != 1:
            cur = await self.conn.execute(
                """UPDATE potd_posts SET problem_id = ?, channel_id = ?, timezone = ?, claimed_at = ?
                   WHERE guild_id = ? AND post_date = ? AND message_id IS NULL AND claimed_at < ?""",
                (problem_id, channel_id, tz_name, to_db(now), guild_id, day.isoformat(), to_db(now - stale_after)))
        await self.conn.commit()
        return await self.get_post_by_date(guild_id, day) if cur.rowcount == 1 else None

    async def finish_post(self, post_id: int, message_id: int) -> None:
        await self.conn.execute("UPDATE potd_posts SET message_id = ? WHERE id = ?", (message_id, post_id))
        await self.conn.commit()

    async def delete_post(self, post_id: int) -> None:
        await self.conn.execute("DELETE FROM potd_posts WHERE id = ?", (post_id,))   # progress rows cascade
        await self.conn.commit()

    async def history(self, guild_id: int) -> list[tuple[str, date]]:
        rows = await self._all("SELECT problem_id, post_date FROM potd_posts WHERE guild_id = ?", (guild_id,))
        return [(r["problem_id"], date.fromisoformat(r["post_date"])) for r in rows]

    async def sent_posts(self, guild_id: int) -> list[Post]:
        rows = await self._all(
            "SELECT * FROM potd_posts WHERE guild_id = ? AND message_id IS NOT NULL ORDER BY post_date", (guild_id,))
        return [_post(r) for r in rows]

    # ------------------------------------------------------------------------------------------- progress

    async def get_progress(self, post_id: int, user_id: int) -> Progress:
        row = await self._one("SELECT * FROM potd_progress WHERE post_id = ? AND user_id = ?", (post_id, user_id))
        if not row:
            return Progress()
        return Progress(row["hints_used"], row["attempts"], from_db(row["last_attempt_at"]),
                        from_db(row["solved_at"]), from_db(row["revealed_at"]))

    async def _ensure_progress(self, post_id: int, user_id: int) -> None:
        await self.conn.execute("INSERT INTO potd_progress (post_id, user_id) VALUES (?, ?) ON CONFLICT DO NOTHING",
                                (post_id, user_id))

    async def use_hint(self, post_id: int, user_id: int, max_hints: int) -> int:
        """Advance the user's hint counter (never past max_hints). Returns the new count."""
        await self._ensure_progress(post_id, user_id)
        await self.conn.execute(
            "UPDATE potd_progress SET hints_used = MIN(hints_used + 1, ?) WHERE post_id = ? AND user_id = ?",
            (max_hints, post_id, user_id))
        await self.conn.commit()
        return (await self.get_progress(post_id, user_id)).hints_used

    async def record_attempt(self, post_id: int, user_id: int, now: datetime) -> int:
        await self._ensure_progress(post_id, user_id)
        await self.conn.execute(
            "UPDATE potd_progress SET attempts = attempts + 1, last_attempt_at = ? WHERE post_id = ? AND user_id = ?",
            (to_db(now), post_id, user_id))
        await self.conn.commit()
        return (await self.get_progress(post_id, user_id)).attempts

    async def mark_solved(self, post_id: int, user_id: int, now: datetime) -> bool:
        """True only for the first solve, and never after the solution was viewed (so credit cannot be duplicated)."""
        await self._ensure_progress(post_id, user_id)
        cur = await self.conn.execute(
            "UPDATE potd_progress SET solved_at = ? WHERE post_id = ? AND user_id = ? "
            "AND solved_at IS NULL AND revealed_at IS NULL", (to_db(now), post_id, user_id))
        await self.conn.commit()
        return cur.rowcount == 1

    async def mark_revealed(self, post_id: int, user_id: int, now: datetime) -> None:
        await self._ensure_progress(post_id, user_id)
        await self.conn.execute(
            "UPDATE potd_progress SET revealed_at = COALESCE(revealed_at, ?) WHERE post_id = ? AND user_id = ?",
            (to_db(now), post_id, user_id))
        await self.conn.commit()

    async def solved_post_ids(self, guild_id: int, user_id: int) -> set[int]:
        rows = await self._all(
            """SELECT pr.post_id FROM potd_progress pr JOIN potd_posts po ON po.id = pr.post_id
               WHERE po.guild_id = ? AND pr.user_id = ? AND pr.solved_at IS NOT NULL""", (guild_id, user_id))
        return {r["post_id"] for r in rows}

    async def solved_rows(self, guild_id: int) -> list[tuple[int, int, int]]:
        """(user_id, post_id, hints_used) for every solve in the server."""
        rows = await self._all(
            """SELECT pr.user_id, pr.post_id, pr.hints_used FROM potd_progress pr
               JOIN potd_posts po ON po.id = pr.post_id
               WHERE po.guild_id = ? AND po.message_id IS NOT NULL AND pr.solved_at IS NOT NULL""", (guild_id,))
        return [(r["user_id"], r["post_id"], r["hints_used"]) for r in rows]
