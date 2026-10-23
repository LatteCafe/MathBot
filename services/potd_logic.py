"""Pure Problem-of-the-Day logic: scheduling, problem selection, streaks. No database, no Discord, no clock reads
(every function takes `now` explicitly), so all of it is deterministic and easy to test."""
from __future__ import annotations

import random
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from .problem_bank import Problem, ProblemBank

MAX_LATE = timedelta(hours=6)             # a post later than this after its scheduled time is skipped, not sent late
CLAIM_STALE_AFTER = timedelta(minutes=10)  # an unsent claim older than this is considered abandoned
ATTEMPT_COOLDOWN = timedelta(seconds=10)
LEVEL_WEIGHTS = {"core": 4, "advanced": 4, "challenge": 2}   # used when a server's difficulty is "any"


# ---------------------------------------------------------------------------------------------------- scheduling

def scheduled_instant(day: date, hour: int, minute: int, tz: ZoneInfo) -> datetime:
    """The moment `hour:minute` occurs on `day` in `tz`, as an aware UTC datetime (DST gaps resolve via zoneinfo)."""
    return datetime.combine(day, time(hour, minute), tzinfo=tz).astimezone(timezone.utc)


def due_post_date(now: datetime, tz: ZoneInfo, hour: int, minute: int, max_late: timedelta = MAX_LATE) -> date | None:
    """The local date that should be posted right now, or None.

    Posts once the scheduled time has passed. If the bot was down and comes back within `max_late`, it still posts
    (late, but the same local day). Beyond that the day is skipped: no backlog is ever posted, so a long outage
    cannot cause a burst of messages. Whether a post for that date already exists is decided by the database claim.
    """
    today = now.astimezone(tz).date()
    scheduled = scheduled_instant(today, hour, minute, tz)
    if now < scheduled or now - scheduled > max_late:
        return None
    return today


def next_post_time(now: datetime, tz: ZoneInfo, hour: int, minute: int, posted_today: bool) -> datetime:
    today = now.astimezone(tz).date()
    todays = scheduled_instant(today, hour, minute, tz)
    if not posted_today and now - todays <= MAX_LATE:
        return todays if now < todays else now            # due now (the next scheduler tick will post)
    return scheduled_instant(today + timedelta(days=1), hour, minute, tz)


def is_open(post_date: date, tz: ZoneInfo, now: datetime) -> bool:
    """A problem accepts answers only during its own local calendar day."""
    return now.astimezone(tz).date() == post_date


# ---------------------------------------------------------------------------------------------------- selection

def select_problem(bank: ProblemBank, difficulty: str, history: list[tuple[str, date]], today: date,
                   repeat_window_days: int, rng: random.Random) -> Problem:
    """Pick the next problem.

    1. Only problems of the chosen difficulty ("any" = all levels).
    2. Never repeat a problem posted within the repeat window; if every problem is inside the window, fall back to
       the least recently posted ones (the bank is finite, so repeats are eventually unavoidable).
    3. Rotate subjects: prefer the subject that was posted longest ago (or never).
    4. Within that, with "any" difficulty pick a level by weight, then a problem uniformly.
    """
    pool = list(bank) if difficulty == "any" else bank.by_level(difficulty)
    if not pool:
        raise LookupError(f"The problem bank has no problems at difficulty {difficulty!r}.")

    last_posted: dict[str, date] = {}
    for problem_id, day in history:
        if bank.get(problem_id) is not None:
            last_posted[problem_id] = max(day, last_posted.get(problem_id, date.min))

    cutoff = today - timedelta(days=repeat_window_days)
    candidates = [p for p in pool if last_posted.get(p.id, date.min) <= cutoff]
    if not candidates:
        oldest = min(last_posted.get(p.id, date.min) for p in pool)
        candidates = [p for p in pool if last_posted.get(p.id, date.min) == oldest]

    subject_last: dict[str, date] = {}
    for problem_id, day in last_posted.items():
        subject = bank.get(problem_id).subject
        subject_last[subject] = max(day, subject_last.get(subject, date.min))
    stalest = min(subject_last.get(p.subject, date.min) for p in candidates)
    candidates = [p for p in candidates if subject_last.get(p.subject, date.min) == stalest]

    if difficulty == "any":
        levels = sorted({p.level for p in candidates})
        level = rng.choices(levels, weights=[LEVEL_WEIGHTS[lv] for lv in levels])[0]
        candidates = [p for p in candidates if p.level == level]
    return rng.choice(sorted(candidates, key=lambda p: p.id))          # sorted: reproducible for a given seed


# ---------------------------------------------------------------------------------------------------- streaks

def compute_streaks(entries: list[tuple[date, bool]], today: date) -> tuple[int, int]:
    """(current streak, best streak) from (post_date, solved) for every post, oldest first.

    A streak counts consecutive POSTS solved, not calendar days, so a day on which the bot posted nothing (downtime)
    cannot break anyone's streak. Today's problem is still open: if it is unsolved it neither counts nor breaks the
    current streak yet.
    """
    entries = sorted(entries, key=lambda e: e[0])
    best = run = 0
    for _, solved in entries:
        run = run + 1 if solved else 0
        best = max(best, run)

    i = len(entries) - 1
    if i >= 0 and entries[i][0] >= today and not entries[i][1]:
        i -= 1
    current = 0
    while i >= 0 and entries[i][1]:
        current += 1
        i -= 1
    return current, best
