"""Problem of the Day: the rules. Talks to the database and the math engine; knows nothing about Discord."""
from __future__ import annotations

import enum
import logging
import random
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from database.potd_repo import DIFFICULTIES, GuildSettings, Post, PotdRepository
from math_engine.errors import MathError

from .answers import Verdict, check_answer
from .potd_logic import (ATTEMPT_COOLDOWN, CLAIM_STALE_AFTER, compute_streaks, due_post_date, is_open,
                         next_post_time, select_problem)
from .problem_bank import Problem, ProblemBank

log = logging.getLogger(__name__)


class AlreadyPostedError(Exception):
    def __init__(self, post: Post) -> None:
        super().__init__(f"A problem was already posted for {post.post_date}.")
        self.post = post


class SettingsError(ValueError):
    """Invalid settings; the message is safe to show to an admin."""


@dataclass(frozen=True)
class PreparedPost:
    post: Post
    problem: Problem


@dataclass(frozen=True)
class PostContext:
    post: Post
    problem: Problem
    is_open: bool


class HintStatus(enum.Enum):
    OK = "ok"
    NO_MORE = "no_more"
    NO_HINTS = "no_hints"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class HintResult:
    status: HintStatus
    text: str | None = None
    number: int = 0
    total: int = 0


class SubmitStatus(enum.Enum):
    CORRECT = "correct"
    INCORRECT = "incorrect"
    INVALID = "invalid"
    ALREADY_SOLVED = "already_solved"
    REVEALED = "revealed"
    CLOSED = "closed"
    COOLDOWN = "cooldown"
    OUT_OF_ATTEMPTS = "out_of_attempts"
    UNAVAILABLE = "unavailable"
    ERROR = "error"


@dataclass(frozen=True)
class SubmitResult:
    status: SubmitStatus
    message: str | None = None
    attempts: int = 0
    attempts_left: int | None = None
    retry_after: float = 0.0
    streak: int = 0
    problem: Problem | None = None


class RevealStatus(enum.Enum):
    CONFIRM_NEEDED = "confirm_needed"
    SHOWN = "shown"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class RevealResult:
    status: RevealStatus
    problem: Problem | None = None
    forfeited: bool = False


@dataclass(frozen=True)
class UserStats:
    solved: int
    current_streak: int
    best_streak: int
    solved_without_hints: int
    total_posts: int
    by_subject: dict[str, int]


@dataclass(frozen=True)
class LeaderboardRow:
    rank: int
    user_id: int
    solved: int
    current_streak: int
    best_streak: int


def validate_timezone(name: str) -> str:
    try:
        ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, OSError):
        raise SettingsError(f"Unknown timezone {name!r}. Use a name like 'America/Toronto' or 'Europe/London' "
                            "(you can pick from the suggestions as you type).") from None
    return name


class PotdService:
    def __init__(self, repo: PotdRepository, bank: ProblemBank, engine, rng: random.Random | None = None) -> None:
        self.repo, self.bank, self.engine = repo, bank, engine
        self.rng = rng or random.Random()

    # ------------------------------------------------------------------------------------------ settings

    async def get_settings(self, guild_id: int) -> GuildSettings:
        return await self.repo.get_settings(guild_id)

    async def update_settings(self, guild_id: int, **changes) -> GuildSettings:
        """Apply only the provided (non-None) changes, validating each, and save."""
        changes = {k: v for k, v in changes.items() if v is not None}
        if "timezone" in changes:
            validate_timezone(changes["timezone"])
        if "difficulty" in changes and changes["difficulty"] not in DIFFICULTIES:
            raise SettingsError(f"Difficulty must be one of {', '.join(DIFFICULTIES)}.")
        if "difficulty" in changes and changes["difficulty"] != "any" and not self.bank.by_level(changes["difficulty"]):
            raise SettingsError(f"The problem bank has no {changes['difficulty']} problems yet.")
        if "hour" in changes and not 0 <= changes["hour"] <= 23:
            raise SettingsError("The hour must be between 0 and 23.")
        if "minute" in changes and not 0 <= changes["minute"] <= 59:
            raise SettingsError("The minute must be between 0 and 59.")
        if "repeat_window_days" in changes and changes["repeat_window_days"] < 1:
            raise SettingsError("The repeat window must be at least 1 day.")
        settings = (await self.repo.get_settings(guild_id)).with_changes(**changes)
        if settings.enabled and settings.channel_id is None:
            raise SettingsError("Choose a channel before enabling daily posts.")
        await self.repo.save_settings(settings)
        return settings

    async def next_post_at(self, settings: GuildSettings, now: datetime) -> datetime:
        today = now.astimezone(settings.tz).date()
        existing = await self.repo.get_post_by_date(settings.guild_id, today)
        return next_post_time(now, settings.tz, settings.hour, settings.minute, posted_today=existing is not None)

    # ------------------------------------------------------------------------------------------ posting

    async def _prepare(self, settings: GuildSettings, day: date, channel_id: int | None, now: datetime) -> PreparedPost | None:
        history = await self.repo.history(settings.guild_id)
        problem = select_problem(self.bank, settings.difficulty, history, day, settings.repeat_window_days, self.rng)
        post = await self.repo.claim_post(settings.guild_id, day, problem.id, channel_id, settings.timezone, now,
                                          CLAIM_STALE_AFTER)
        return PreparedPost(post, problem) if post else None

    async def due_posts(self, now: datetime, skip: set[int] | frozenset[int] = frozenset()) -> list[PreparedPost]:
        """Claim and return every post that is due now. The caller sends each one, then calls complete_post (or
        abandon_post if sending failed)."""
        prepared = []
        for settings in await self.repo.enabled_guilds():
            if settings.guild_id in skip:
                continue
            try:
                day = due_post_date(now, settings.tz, settings.hour, settings.minute)
                if day is None:
                    continue
                item = await self._prepare(settings, day, settings.channel_id, now)
            except (ZoneInfoNotFoundError, ValueError, LookupError) as exc:
                log.error("Cannot schedule Problem of the Day for guild %s: %s", settings.guild_id, exc)
                continue
            if item:
                prepared.append(item)
        return prepared

    async def post_now(self, guild_id: int, channel_id: int, now: datetime, replace: bool = False) -> PreparedPost:
        """Manual post for today. Raises AlreadyPostedError unless `replace` (which discards today's post and its progress)."""
        settings = await self.repo.get_settings(guild_id)
        day = now.astimezone(settings.tz).date()
        existing = await self.repo.get_post_by_date(guild_id, day)
        if existing:
            if not replace:
                raise AlreadyPostedError(existing)
            await self.repo.delete_post(existing.id)
        item = await self._prepare(settings, day, channel_id, now)
        if item is None:      # lost a race with the scheduler
            raise AlreadyPostedError(await self.repo.get_post_by_date(guild_id, day))
        return item

    async def complete_post(self, post_id: int, message_id: int) -> None:
        await self.repo.finish_post(post_id, message_id)

    async def abandon_post(self, post_id: int) -> None:
        await self.repo.delete_post(post_id)

    # ------------------------------------------------------------------------------------------ interactions

    async def context(self, message_id: int, now: datetime) -> PostContext | None:
        post = await self.repo.get_post_by_message(message_id)
        problem = self.bank.get(post.problem_id) if post else None
        if post is None or problem is None:
            return None
        return PostContext(post, problem, is_open(post.post_date, ZoneInfo(post.timezone), now))

    async def hint(self, message_id: int, user_id: int, now: datetime) -> HintResult:
        ctx = await self.context(message_id, now)
        if ctx is None:
            return HintResult(HintStatus.UNAVAILABLE)
        total = len(ctx.problem.hints)
        if total == 0:
            return HintResult(HintStatus.NO_HINTS)
        used = (await self.repo.get_progress(ctx.post.id, user_id)).hints_used
        if used >= total:
            return HintResult(HintStatus.NO_MORE, ctx.problem.hints[-1], used, total)
        number = await self.repo.use_hint(ctx.post.id, user_id, total)
        return HintResult(HintStatus.OK, ctx.problem.hints[number - 1], number, total)

    async def submit(self, message_id: int, user_id: int, text: str, now: datetime) -> SubmitResult:
        ctx = await self.context(message_id, now)
        if ctx is None:
            return SubmitResult(SubmitStatus.UNAVAILABLE)
        problem, post = ctx.problem, ctx.post
        progress = await self.repo.get_progress(post.id, user_id)

        if progress.solved_at:
            return SubmitResult(SubmitStatus.ALREADY_SOLVED, attempts=progress.attempts, problem=problem)
        if progress.revealed_at:
            return SubmitResult(SubmitStatus.REVEALED, problem=problem)
        if not ctx.is_open:
            return SubmitResult(SubmitStatus.CLOSED, problem=problem)
        if progress.last_attempt_at and now - progress.last_attempt_at < ATTEMPT_COOLDOWN:
            wait = (ATTEMPT_COOLDOWN - (now - progress.last_attempt_at)).total_seconds()
            return SubmitResult(SubmitStatus.COOLDOWN, retry_after=wait, attempts=progress.attempts, problem=problem)
        if problem.max_attempts is not None and progress.attempts >= problem.max_attempts:
            return SubmitResult(SubmitStatus.OUT_OF_ATTEMPTS, attempts=progress.attempts, attempts_left=0, problem=problem)

        try:
            check = await check_answer(problem, text, self.engine)
        except MathError as exc:        # timeout / worker failure: the user is not penalised with an attempt
            return SubmitResult(SubmitStatus.ERROR, str(exc), attempts=progress.attempts, problem=problem)
        if check.verdict is Verdict.INVALID:
            return SubmitResult(SubmitStatus.INVALID, check.message, attempts=progress.attempts, problem=problem)

        attempts = await self.repo.record_attempt(post.id, user_id, now)
        left = None if problem.max_attempts is None else max(0, problem.max_attempts - attempts)
        if check.verdict is Verdict.INCORRECT:
            return SubmitResult(SubmitStatus.INCORRECT, attempts=attempts, attempts_left=left, problem=problem)

        if not await self.repo.mark_solved(post.id, user_id, now):
            # Lost a race: the solution was revealed (or an earlier submission solved it) while we were grading.
            # Never tell the user "Correct!" for credit that was not recorded.
            latest = await self.repo.get_progress(post.id, user_id)
            status = SubmitStatus.ALREADY_SOLVED if latest.solved_at else SubmitStatus.REVEALED
            return SubmitResult(status, attempts=attempts, problem=problem)
        streak = (await self._streak(post.guild_id, user_id, now, ZoneInfo(post.timezone)))[0]
        return SubmitResult(SubmitStatus.CORRECT, attempts=attempts, streak=streak, problem=problem)

    async def reveal(self, message_id: int, user_id: int, now: datetime, confirmed: bool = False) -> RevealResult:
        """Show the solution. Doing so BEFORE solving an open problem forfeits credit, so that needs confirmation."""
        ctx = await self.context(message_id, now)
        if ctx is None:
            return RevealResult(RevealStatus.UNAVAILABLE)
        progress = await self.repo.get_progress(ctx.post.id, user_id)
        if progress.solved_at or progress.revealed_at or not ctx.is_open:
            return RevealResult(RevealStatus.SHOWN, ctx.problem)
        if not confirmed:
            return RevealResult(RevealStatus.CONFIRM_NEEDED, ctx.problem)
        await self.repo.mark_revealed(ctx.post.id, user_id, now)
        return RevealResult(RevealStatus.SHOWN, ctx.problem, forfeited=True)

    # ------------------------------------------------------------------------------------------ statistics

    async def _streak(self, guild_id: int, user_id: int, now: datetime, tz: ZoneInfo) -> tuple[int, int]:
        posts = await self.repo.sent_posts(guild_id)
        solved = await self.repo.solved_post_ids(guild_id, user_id)
        return compute_streaks([(p.post_date, p.id in solved) for p in posts], now.astimezone(tz).date())

    async def stats(self, guild_id: int, user_id: int, now: datetime) -> UserStats:
        settings = await self.repo.get_settings(guild_id)
        posts = await self.repo.sent_posts(guild_id)
        by_id = {p.id: p for p in posts}
        mine = [(post_id, hints) for uid, post_id, hints in await self.repo.solved_rows(guild_id) if uid == user_id]
        by_subject: dict[str, int] = {}
        for post_id, _ in mine:
            problem = self.bank.get(by_id[post_id].problem_id) if post_id in by_id else None
            if problem:
                by_subject[problem.subject_label] = by_subject.get(problem.subject_label, 0) + 1
        current, best = await self._streak(guild_id, user_id, now, settings.tz)
        return UserStats(len(mine), current, best, sum(1 for _, hints in mine if hints == 0), len(posts), by_subject)

    async def leaderboard(self, guild_id: int, now: datetime, limit: int = 10) -> list[LeaderboardRow]:
        settings = await self.repo.get_settings(guild_id)
        posts = await self.repo.sent_posts(guild_id)
        today = now.astimezone(settings.tz).date()
        solved_by_user: dict[int, set[int]] = {}
        for user_id, post_id, _ in await self.repo.solved_rows(guild_id):
            solved_by_user.setdefault(user_id, set()).add(post_id)
        rows = []
        for user_id, solved in solved_by_user.items():
            current, best = compute_streaks([(p.post_date, p.id in solved) for p in posts], today)
            rows.append((user_id, len(solved), current, best))
        rows.sort(key=lambda r: (-r[1], -r[3], -r[2], r[0]))            # solves, then best streak, then current streak
        ranked, previous_key, rank = [], None, 0
        for position, (user_id, solved, current, best) in enumerate(rows, start=1):
            key = (solved, best, current)
            if key != previous_key:
                rank, previous_key = position, key                       # tied users share a rank
            ranked.append(LeaderboardRow(rank, user_id, solved, current, best))
        return ranked[:limit]
