import random
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from services.potd_logic import (MAX_LATE, compute_streaks, due_post_date, is_open, next_post_time, scheduled_instant,
                                 select_problem)
from tests.potd_support import make_bank

UTC = timezone.utc
TORONTO = ZoneInfo("America/Toronto")      # UTC-4 in October (EDT), UTC-5 in winter
D = date


def utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


# ------------------------------------------------------------------------------------------ scheduling

def test_a_post_is_due_from_the_scheduled_time_until_the_late_limit():
    # 09:00 Toronto on 19 Oct 2026 is 13:00 UTC.
    assert due_post_date(utc(2026, 10, 19, 12, 59), TORONTO, 9, 0) is None
    assert due_post_date(utc(2026, 10, 19, 13, 0), TORONTO, 9, 0) == D(2026, 10, 19)
    assert due_post_date(utc(2026, 10, 19, 15, 30), TORONTO, 9, 0) == D(2026, 10, 19)
    assert due_post_date(utc(2026, 10, 19, 19, 0), TORONTO, 9, 0) == D(2026, 10, 19)        # exactly 6h late: still ok
    assert due_post_date(utc(2026, 10, 19, 19, 1), TORONTO, 9, 0) is None                   # too late: skipped, not backlogged


def test_the_date_is_the_servers_local_date_not_the_utc_date():
    # 02:00 UTC on the 20th is 22:00 on the 19th in Toronto.
    assert due_post_date(utc(2026, 10, 20, 2, 0), TORONTO, 21, 0) == D(2026, 10, 19)
    assert due_post_date(utc(2026, 10, 20, 12, 0), TORONTO, 9, 0) is None                    # 08:00 on the 20th: not yet


def test_half_hour_offset_timezones_work():
    kolkata = ZoneInfo("Asia/Kolkata")               # UTC+5:30, so 09:00 is 03:30 UTC
    assert due_post_date(utc(2026, 10, 19, 3, 29), kolkata, 9, 0) is None
    assert due_post_date(utc(2026, 10, 19, 3, 30), kolkata, 9, 0) == D(2026, 10, 19)


def test_each_local_day_yields_exactly_one_due_date_across_a_whole_week():
    """Sweep every minute of a week: the due date changes only once a day, never skips a day, never repeats one."""
    seen = []
    now = utc(2026, 10, 15, 0, 0)
    while now < utc(2026, 10, 22, 0, 0):
        day = due_post_date(now, TORONTO, 9, 0)
        if day and (not seen or seen[-1] != day):
            seen.append(day)
        now += timedelta(minutes=1)
    assert seen == [D(2026, 10, d) for d in range(15, 22)]


def test_spring_forward_a_nonexistent_local_time_still_posts_once_that_day():
    # In Toronto 02:30 does not exist on 8 March 2026 (clocks jump 02:00 -> 03:00).
    assert due_post_date(utc(2026, 3, 8, 5, 0), TORONTO, 2, 30) is None
    assert due_post_date(utc(2026, 3, 8, 12, 0), TORONTO, 2, 30) == D(2026, 3, 8)
    assert due_post_date(utc(2026, 3, 9, 12, 0), TORONTO, 2, 30) == D(2026, 3, 9)


def test_fall_back_an_ambiguous_local_time_posts_once_and_uses_the_first_occurrence():
    # 01:30 on 1 Nov 2026 happens twice in Toronto; the first is 05:30 UTC (EDT).
    assert scheduled_instant(D(2026, 11, 1), 1, 30, TORONTO) == utc(2026, 11, 1, 5, 30)
    assert due_post_date(utc(2026, 11, 1, 6, 0), TORONTO, 1, 30) == D(2026, 11, 1)


def test_the_utc_offset_changes_with_daylight_saving():
    assert scheduled_instant(D(2026, 7, 1), 9, 0, TORONTO) == utc(2026, 7, 1, 13, 0)      # EDT
    assert scheduled_instant(D(2026, 12, 1), 9, 0, TORONTO) == utc(2026, 12, 1, 14, 0)    # EST


def test_next_post_time():
    nine = lambda d: scheduled_instant(d, 9, 0, TORONTO)  # noqa: E731
    before = utc(2026, 10, 19, 11, 0)
    assert next_post_time(before, TORONTO, 9, 0, posted_today=False) == nine(D(2026, 10, 19))
    assert next_post_time(before, TORONTO, 9, 0, posted_today=True) == nine(D(2026, 10, 20))
    due_now = utc(2026, 10, 19, 14, 0)
    assert next_post_time(due_now, TORONTO, 9, 0, posted_today=False) == due_now             # the next tick will post it
    assert next_post_time(due_now, TORONTO, 9, 0, posted_today=True) == nine(D(2026, 10, 20))
    too_late = utc(2026, 10, 19, 13, 0) + MAX_LATE + timedelta(minutes=1)
    assert next_post_time(too_late, TORONTO, 9, 0, posted_today=False) == nine(D(2026, 10, 20))


def test_a_problem_is_open_only_during_its_own_local_day():
    assert is_open(D(2026, 10, 19), TORONTO, utc(2026, 10, 19, 13, 0))
    assert is_open(D(2026, 10, 19), TORONTO, utc(2026, 10, 20, 3, 59, 59))     # 23:59:59 local
    assert not is_open(D(2026, 10, 19), TORONTO, utc(2026, 10, 20, 4, 0))      # midnight local
    assert not is_open(D(2026, 10, 19), TORONTO, utc(2026, 10, 18, 20, 0))


# ------------------------------------------------------------------------------------------ selection

def pick(bank, difficulty="any", history=(), today=D(2026, 10, 19), window=60, seed=1):
    return select_problem(bank, difficulty, list(history), today, window, random.Random(seed))


def test_difficulty_filters_the_pool():
    bank = make_bank(("a", "analysis", "core"), ("b", "analysis", "advanced"), ("c", "analysis", "challenge"))
    for seed in range(10):
        assert pick(bank, "challenge", seed=seed).id == "c"
        assert pick(bank, "core", seed=seed).id == "a"
    with pytest.raises(LookupError):
        pick(make_bank(("a", "analysis", "core")), "challenge")


def test_recent_problems_are_not_repeated():
    bank = make_bank(*[(f"p{i}", "analysis", "core") for i in range(4)])
    history = [("p0", D(2026, 10, 18)), ("p1", D(2026, 10, 17)), ("p2", D(2026, 10, 1))]
    for seed in range(20):
        assert pick(bank, history=history, window=60, seed=seed).id == "p3"        # the only one outside the window


def test_the_repeat_window_boundary_is_exact():
    bank = make_bank(("old", "analysis", "core"), ("new", "analysis", "core"))
    today = D(2026, 10, 19)
    exactly_window_ago = [("old", today - timedelta(days=10)), ("new", today - timedelta(days=1))]
    assert pick(bank, history=exactly_window_ago, today=today, window=10).id == "old"          # 10 days ago: eligible again
    one_day_short = [("old", today - timedelta(days=9)), ("new", today - timedelta(days=1))]
    assert pick(bank, history=one_day_short, today=today, window=10).id == "old"               # fallback: least recent


def test_when_everything_is_inside_the_window_the_least_recently_posted_is_chosen():
    bank = make_bank(*[(f"p{i}", "analysis", "core") for i in range(3)])
    history = [("p0", D(2026, 10, 18)), ("p1", D(2026, 10, 10)), ("p2", D(2026, 10, 14))]
    assert pick(bank, history=history, window=365).id == "p1"


def test_subjects_rotate_longest_ago_first_and_never_used_first_of_all():
    bank = make_bank(("a1", "analysis", "core"), ("a2", "analysis", "core"), ("g1", "abstract_algebra", "core"),
                     ("g2", "abstract_algebra", "core"), ("t1", "topology", "core"), ("t2", "topology", "core"))
    history = [("a1", D(2026, 10, 18)), ("g1", D(2026, 10, 10))]
    for seed in range(15):
        assert pick(bank, history=history, seed=seed).subject == "topology"          # never used
    history.append(("t1", D(2026, 10, 5)))
    for seed in range(15):
        assert pick(bank, history=history, seed=seed).subject == "topology"          # 5 Oct is older than 10 Oct and 18 Oct
    history.append(("t2", D(2026, 10, 17)))
    for seed in range(15):
        assert pick(bank, history=history, seed=seed).subject == "abstract_algebra"  # now the stalest


def test_selection_is_reproducible_for_a_given_seed_and_varies_across_seeds():
    bank = make_bank(*[(f"p{i}", "analysis", "core") for i in range(20)])
    assert pick(bank, seed=7).id == pick(bank, seed=7).id
    assert len({pick(bank, seed=s).id for s in range(40)}) > 5


def test_mixed_difficulty_follows_the_level_weights():
    bank = make_bank(*[(f"c{i}", "analysis", "core") for i in range(5)], *[(f"a{i}", "analysis", "advanced") for i in range(5)],
                     *[(f"h{i}", "analysis", "challenge") for i in range(5)])
    rng = random.Random(2026)
    counts = Counter(select_problem(bank, "any", [], D(2026, 10, 19), 60, rng).level for _ in range(5000))
    share = {level: n / 5000 for level, n in counts.items()}
    assert abs(share["core"] - 0.4) < 0.03 and abs(share["advanced"] - 0.4) < 0.03 and abs(share["challenge"] - 0.2) < 0.03


def test_ids_missing_from_the_bank_are_ignored_in_the_history():
    bank = make_bank(("a", "analysis", "core"), ("b", "topology", "core"))
    assert pick(bank, history=[("deleted-problem", D(2026, 10, 18))]).id in {"a", "b"}


def test_a_long_simulation_never_repeats_inside_the_window_while_that_is_possible():
    bank = make_bank(*[(f"p{i}", ["analysis", "topology", "geometry"][i % 3], ["core", "advanced"][i % 2]) for i in range(12)])
    rng, history, window = random.Random(5), [], 8
    start = D(2026, 1, 1)
    for n in range(100):
        today = start + timedelta(days=n)
        chosen = select_problem(bank, "any", history, today, window, rng)
        recent = {pid for pid, day in history if (today - day).days < window}
        assert chosen.id not in recent, f"day {n}: {chosen.id} repeated within {window} days"
        history.append((chosen.id, today))
    assert len({pid for pid, _ in history}) == 12                                  # and the whole bank gets used


# ------------------------------------------------------------------------------------------ streaks

TODAY = D(2026, 10, 19)


def entries(*flags, end=TODAY):
    """Flags for consecutive daily posts, the last one on `end`."""
    return [(end - timedelta(days=len(flags) - 1 - i), f) for i, f in enumerate(flags)]


@pytest.mark.parametrize("flags,expected", [
    ((), (0, 0)),
    ((True,), (1, 1)),
    ((True, True, True), (3, 3)),
    ((False,), (0, 0)),
    ((True, True, False), (2, 2)),                  # today's problem is OPEN and unsolved: it neither counts nor breaks
    ((True, True, True, True), (4, 4)),
    ((True, False, True, True), (2, 2)),            # the gap resets the run
    ((True, True, True, False, True), (1, 3)),
    ((False, False, True), (1, 1)),
])
def test_streaks_when_the_last_post_is_today(flags, expected):
    if flags and flags[-1] is False and len(flags) > 1:
        # an unsolved but still-open "today" does not break the streak built before it
        before = compute_streaks(entries(*flags[:-1], end=TODAY - timedelta(days=1)), TODAY)
        assert compute_streaks(entries(*flags), TODAY)[0] == before[0]
    assert compute_streaks(entries(*flags), TODAY) == expected


def test_an_unsolved_problem_from_a_past_day_breaks_the_current_streak():
    past = entries(True, True, False, end=TODAY - timedelta(days=1))                 # last post was yesterday, unsolved
    assert compute_streaks(past, TODAY) == (0, 2)


def test_solving_today_extends_the_streak():
    assert compute_streaks(entries(True, True, True), TODAY) == (3, 3)


def test_days_without_a_post_do_not_break_a_streak():
    """The bot was down on 17 and 18 Oct: posts exist for the 16th and the 19th only. Solving both keeps the streak."""
    two_posts = [(D(2026, 10, 16), True), (D(2026, 10, 19), True)]
    assert compute_streaks(two_posts, TODAY) == (2, 2)


def test_input_order_does_not_matter():
    shuffled = [(D(2026, 10, 19), True), (D(2026, 10, 17), True), (D(2026, 10, 18), True)]
    assert compute_streaks(shuffled, TODAY) == (3, 3)


def test_best_streak_survives_a_later_break():
    flags = (True,) * 5 + (False,) + (True,) * 2
    assert compute_streaks(entries(*flags), TODAY) == (2, 5)
