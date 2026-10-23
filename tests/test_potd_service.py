import asyncio
import random
from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from database.potd_repo import PotdRepository
from math_engine.errors import ComputeTimeout
from services.potd import (AlreadyPostedError, HintStatus, PotdService, RevealStatus, SettingsError, SubmitStatus)
from tests.potd_support import NOW, FailingEngine, InProcessEngine, make_bank, raw

GUILD, CHANNEL, MESSAGE = 100, 500, 555
S = SubmitStatus


def make_env(db, bank, engine=None):
    repo = PotdRepository(db)
    return SimpleNamespace(db=db, repo=repo, bank=bank, service=PotdService(repo, bank, engine or InProcessEngine(), random.Random(1)))


@pytest.fixture
async def env(open_db):
    db = await open_db("potd.sqlite3")
    bank = make_bank(
        raw("num", "analysis", "core", answer="12"),
        raw("quiz", "topology", "advanced", answer_type="choice", answer="B", options=["one", "two", "three"], hints=[]),
    )
    return make_env(db, bank)


@pytest.fixture
async def solo(open_db):
    """A bank with exactly one problem, so which problem gets posted is known."""
    db = await open_db("solo.sqlite3")
    return make_env(db, make_bank(raw("num", "analysis", "core", answer="12")))


async def enable(e, guild=GUILD, channel=CHANNEL, **extra):
    return await e.service.update_settings(guild, enabled=True, channel_id=channel, hour=9, minute=0,
                                           timezone="America/Toronto", **extra)


async def posted(e, guild=GUILD, message_id=MESSAGE, now=NOW):
    await enable(e, guild)
    (item,) = await e.service.due_posts(now)
    await e.service.complete_post(item.post.id, message_id)
    return item


# ------------------------------------------------------------------------------------------ settings

async def test_unconfigured_servers_get_sensible_defaults(env):
    s = await env.service.get_settings(GUILD)
    assert (s.enabled, s.channel_id, s.hour, s.minute, s.timezone, s.difficulty, s.repeat_window_days) == \
        (False, None, 9, 0, "UTC", "any", 60)


async def test_partial_updates_keep_everything_else_and_none_means_unchanged(env):
    await enable(env)
    await env.service.update_settings(GUILD, hour=18, minute=30)
    await env.service.update_settings(GUILD, difficulty="core", hour=None)
    s = await env.service.get_settings(GUILD)
    assert (s.hour, s.minute, s.difficulty, s.timezone, s.channel_id, s.enabled) == (18, 30, "core", "America/Toronto", CHANNEL, True)
    await env.service.update_settings(GUILD, enabled=False)                  # False is a real change, not "unchanged"
    assert not (await env.service.get_settings(GUILD)).enabled


@pytest.mark.parametrize("changes,fragment", [
    ({"timezone": "Mars/Olympus"}, "Unknown timezone"), ({"timezone": ""}, "Unknown timezone"),
    ({"timezone": "../../etc/passwd"}, "Unknown timezone"),
    ({"difficulty": "easy"}, "Difficulty must be"), ({"difficulty": "challenge"}, "no challenge problems"),
    ({"hour": 24}, "hour"), ({"hour": -1}, "hour"), ({"minute": 60}, "minute"), ({"repeat_window_days": 0}, "at least 1"),
])
async def test_invalid_settings_are_rejected_and_nothing_is_saved(env, changes, fragment):
    await env.service.update_settings(GUILD, hour=7)
    with pytest.raises(SettingsError, match=fragment):
        await env.service.update_settings(GUILD, **changes)
    assert (await env.service.get_settings(GUILD)).hour == 7


async def test_enabling_requires_a_channel(env):
    with pytest.raises(SettingsError, match="Choose a channel"):
        await env.service.update_settings(GUILD, enabled=True)
    assert not (await env.service.get_settings(GUILD)).enabled


async def test_settings_are_per_server(env):
    await enable(env, guild=1)
    await env.service.update_settings(2, hour=22)
    assert (await env.service.get_settings(1)).hour == 9 and (await env.service.get_settings(2)).hour == 22
    assert not (await env.service.get_settings(2)).enabled


# ------------------------------------------------------------------------------------------ the daily post

async def test_nothing_is_due_for_disabled_or_unconfigured_servers(env):
    assert await env.service.due_posts(NOW) == []
    await env.service.update_settings(GUILD, hour=9, timezone="America/Toronto")      # configured but not enabled
    assert await env.service.due_posts(NOW) == []


async def test_a_post_is_claimed_once_and_never_duplicated(env):
    await enable(env)
    assert await env.service.due_posts(NOW - timedelta(hours=2)) == []                  # 08:00 local: too early
    (item,) = await env.service.due_posts(NOW)
    assert item.post.guild_id == GUILD and item.post.post_date == date(2026, 10, 19) and item.post.message_id is None
    assert await env.service.due_posts(NOW) == []                                       # claimed: not offered again
    await env.service.complete_post(item.post.id, MESSAGE)
    assert await env.service.due_posts(NOW + timedelta(minutes=1)) == []
    assert (await env.repo.get_post_by_message(MESSAGE)).problem_id == item.problem.id


async def test_concurrent_scheduler_runs_cannot_double_post(env):
    await enable(env)
    results = await asyncio.gather(*[env.service.due_posts(NOW) for _ in range(5)])
    assert sum(len(r) for r in results) == 1


async def test_two_servers_are_scheduled_independently(env):
    await enable(env, guild=1, channel=11)
    await enable(env, guild=2, channel=22)
    await env.service.update_settings(2, hour=20)                                       # 20:00 local: not due yet
    items = await env.service.due_posts(NOW)
    assert [i.post.guild_id for i in items] == [1]


async def test_late_posts_within_the_window_go_out_but_older_ones_are_skipped(env):
    await enable(env)
    assert len(await env.service.due_posts(NOW + timedelta(hours=5))) == 1              # 15:00 local, 6h after 09:00: ok
    await enable(env, guild=2)
    assert await env.service.due_posts(NOW + timedelta(hours=10)) == []                 # 20:00 local: day skipped


async def test_the_next_day_brings_a_new_post_and_a_new_problem(env):
    first = await posted(env)
    (second,) = await env.service.due_posts(NOW + timedelta(days=1))
    assert second.post.post_date == date(2026, 10, 20) and second.problem.id != first.problem.id


async def test_servers_in_the_skip_set_are_left_alone(env):
    await enable(env)
    assert await env.service.due_posts(NOW, skip={GUILD}) == []
    assert len(await env.service.due_posts(NOW)) == 1


async def test_an_abandoned_claim_can_be_retried_immediately(env):
    await enable(env)
    (item,) = await env.service.due_posts(NOW)
    await env.service.abandon_post(item.post.id)                                        # e.g. the channel was unreachable
    assert len(await env.service.due_posts(NOW + timedelta(minutes=1))) == 1


async def test_a_crash_between_claiming_and_sending_recovers_but_does_not_duplicate(env):
    await enable(env)
    await env.service.due_posts(NOW)                                                    # claimed; the bot "crashes" here
    assert await env.service.due_posts(NOW + timedelta(minutes=5)) == []                # still fresh: someone may be sending
    (again,) = await env.service.due_posts(NOW + timedelta(minutes=11))                 # stale: taken over
    assert again.post.message_id is None
    assert await env.service.due_posts(NOW + timedelta(minutes=12)) == []


async def test_a_broken_timezone_in_the_database_does_not_stop_other_servers(env):
    await enable(env, guild=2, channel=22)
    await env.db.conn.execute("INSERT INTO guild_settings (guild_id, potd_enabled, potd_channel_id, timezone) "
                              "VALUES (1, 1, 11, 'Not/AZone')")
    await env.db.conn.commit()
    assert [i.post.guild_id for i in await env.service.due_posts(NOW)] == [2]


async def test_manual_post_refuses_to_duplicate_unless_replacing(env):
    first = await env.service.post_now(GUILD, CHANNEL, NOW)
    await env.service.complete_post(first.post.id, MESSAGE)
    with pytest.raises(AlreadyPostedError):
        await env.service.post_now(GUILD, CHANNEL, NOW)
    await env.service.submit(MESSAGE, 1, "0", NOW) if first.problem.id == "num" else None
    second = await env.service.post_now(GUILD, CHANNEL, NOW, replace=True)
    assert second.post.id != first.post.id and second.post.channel_id == CHANNEL
    assert await env.repo.get_post_by_message(MESSAGE) is None                          # the old post is gone


async def test_replacing_a_post_discards_its_progress(solo):
    first = await posted(solo)
    await solo.service.submit(MESSAGE, 1, "12", NOW)
    assert await solo.repo.solved_post_ids(GUILD, 1) == {first.post.id}
    await solo.service.post_now(GUILD, CHANNEL, NOW, replace=True)
    assert await solo.repo.solved_post_ids(GUILD, 1) == set()


async def test_next_post_time_accounts_for_whether_today_was_posted(env):
    s = await enable(env)
    assert (await env.service.next_post_at(s, NOW - timedelta(hours=3))).isoformat().startswith("2026-10-19T13:00")
    await posted(env)
    assert (await env.service.next_post_at(s, NOW)).isoformat().startswith("2026-10-20T13:00")


# ------------------------------------------------------------------------------------------ hints

async def test_hints_are_released_one_at_a_time_per_user(solo):
    await posted(solo)
    r = [await solo.service.hint(MESSAGE, 1, NOW) for _ in range(3)]
    assert [(x.status, x.number, x.text) for x in r] == [
        (HintStatus.OK, 1, "first hint"), (HintStatus.OK, 2, "second hint"), (HintStatus.NO_MORE, 2, "second hint")]
    other = await solo.service.hint(MESSAGE, 2, NOW)
    assert (other.status, other.number) == (HintStatus.OK, 1)                           # another user starts from hint 1


async def test_hint_edge_cases(env):
    await posted(env)
    assert (await env.service.hint(999, 1, NOW)).status is HintStatus.UNAVAILABLE
    await env.repo.conn.execute("UPDATE potd_posts SET problem_id = 'quiz'")            # the problem with no hints
    await env.repo.conn.commit()
    assert (await env.service.hint(MESSAGE, 1, NOW)).status is HintStatus.NO_HINTS


async def test_using_hints_does_not_block_solving(solo):
    await posted(solo)
    await solo.service.hint(MESSAGE, 1, NOW)
    assert (await solo.service.submit(MESSAGE, 1, "12", NOW)).status is S.CORRECT


# ------------------------------------------------------------------------------------------ submitting

async def test_a_correct_answer_is_recorded_once(solo):
    item = await posted(solo)
    r = await solo.service.submit(MESSAGE, 1, "12", NOW)
    assert (r.status, r.attempts, r.streak) == (S.CORRECT, 1, 1)
    again = await solo.service.submit(MESSAGE, 1, "12", NOW + timedelta(minutes=1))
    assert again.status is S.ALREADY_SOLVED
    assert await solo.repo.solved_post_ids(GUILD, 1) == {item.post.id}
    assert await solo.repo.mark_solved(item.post.id, 1, NOW) is False                   # the database also refuses a second solve


async def test_wrong_answers_count_attempts_and_are_rate_limited(solo):
    await posted(solo)
    first = await solo.service.submit(MESSAGE, 1, "13", NOW)
    assert (first.status, first.attempts, first.attempts_left) == (S.INCORRECT, 1, None)
    quick = await solo.service.submit(MESSAGE, 1, "14", NOW + timedelta(seconds=3))
    assert quick.status is S.COOLDOWN and 6.9 < quick.retry_after < 7.1 and quick.attempts == 1
    later = await solo.service.submit(MESSAGE, 1, "12", NOW + timedelta(seconds=11))
    assert (later.status, later.attempts) == (S.CORRECT, 2)


async def test_the_cooldown_is_per_user(solo):
    await posted(solo)
    await solo.service.submit(MESSAGE, 1, "13", NOW)
    assert (await solo.service.submit(MESSAGE, 2, "13", NOW)).status is S.INCORRECT


async def test_unreadable_answers_cost_nothing(solo):
    await posted(solo)
    for text in ["foo(1)", "", "1/0", "__import__('os')"]:
        r = await solo.service.submit(MESSAGE, 1, text, NOW)
        assert r.status is S.INVALID and r.attempts == 0, text
    assert (await solo.service.submit(MESSAGE, 1, "12", NOW)).status is S.CORRECT       # no cooldown was triggered


async def test_multiple_choice_problems_allow_only_two_attempts(env):
    await posted(env)
    await env.repo.conn.execute("UPDATE potd_posts SET problem_id = 'quiz'")
    await env.repo.conn.commit()
    r1 = await env.service.submit(MESSAGE, 1, "A", NOW)
    assert (r1.status, r1.attempts_left) == (S.INCORRECT, 1)
    r2 = await env.service.submit(MESSAGE, 1, "C", NOW + timedelta(seconds=11))
    assert (r2.status, r2.attempts_left) == (S.INCORRECT, 0)
    r3 = await env.service.submit(MESSAGE, 1, "B", NOW + timedelta(seconds=30))
    assert r3.status is S.OUT_OF_ATTEMPTS                                               # even the right letter is refused now


async def test_answers_close_at_local_midnight_but_hints_and_solutions_stay_available(solo):
    await posted(solo)
    next_day = NOW + timedelta(hours=15)                                                # 01:00 local on the 20th
    assert (await solo.service.submit(MESSAGE, 1, "12", next_day)).status is S.CLOSED
    assert (await solo.service.hint(MESSAGE, 1, next_day)).status is HintStatus.OK
    shown = await solo.service.reveal(MESSAGE, 1, next_day)
    assert shown.status is RevealStatus.SHOWN and not shown.forfeited                   # no confirmation, nothing forfeited
    assert (await solo.repo.get_progress(1, 1)).revealed_at is None


async def test_the_last_minute_still_counts_and_midnight_does_not(solo):
    await posted(solo)
    assert (await solo.service.submit(MESSAGE, 1, "12", NOW + timedelta(hours=13, minutes=59, seconds=59))).status is S.CORRECT
    assert (await solo.service.submit(MESSAGE, 2, "12", NOW + timedelta(hours=14))).status is S.CLOSED


async def test_an_engine_failure_is_reported_without_charging_an_attempt(open_db):
    db = await open_db()
    e = make_env(db, make_bank(raw("irr", answer="pi/4")), FailingEngine(ComputeTimeout("too slow")))
    await posted(e)
    r = await e.service.submit(MESSAGE, 1, "pi/3", NOW)
    assert r.status is S.ERROR and "too slow" in r.message and r.attempts == 0
    assert (await e.repo.get_progress(1, 1)).attempts == 0


async def test_unknown_and_removed_problems_are_unavailable(solo):
    await posted(solo)
    assert (await solo.service.submit(999, 1, "12", NOW)).status is S.UNAVAILABLE
    solo.service.bank = make_bank(raw("other"))                                         # the problem was deleted from the bank
    assert (await solo.service.submit(MESSAGE, 1, "12", NOW)).status is S.UNAVAILABLE
    assert (await solo.service.reveal(MESSAGE, 1, NOW)).status is RevealStatus.UNAVAILABLE


# ------------------------------------------------------------------------------------------ revealing

async def test_viewing_the_solution_early_needs_confirmation_and_forfeits_credit(solo):
    await posted(solo)
    ask = await solo.service.reveal(MESSAGE, 1, NOW)
    assert ask.status is RevealStatus.CONFIRM_NEEDED
    assert (await solo.repo.get_progress(1, 1)).revealed_at is None                     # asking does not forfeit anything
    shown = await solo.service.reveal(MESSAGE, 1, NOW, confirmed=True)
    assert shown.status is RevealStatus.SHOWN and shown.forfeited
    assert (await solo.service.submit(MESSAGE, 1, "12", NOW)).status is S.REVEALED
    assert await solo.repo.solved_post_ids(GUILD, 1) == set()
    assert (await solo.service.stats(GUILD, 1, NOW)).solved == 0


async def test_viewing_the_solution_after_solving_costs_nothing(solo):
    await posted(solo)
    await solo.service.submit(MESSAGE, 1, "12", NOW)
    shown = await solo.service.reveal(MESSAGE, 1, NOW)
    assert shown.status is RevealStatus.SHOWN and not shown.forfeited
    assert (await solo.service.stats(GUILD, 1, NOW)).solved == 1


async def test_one_users_reveal_does_not_affect_another(solo):
    await posted(solo)
    await solo.service.reveal(MESSAGE, 1, NOW, confirmed=True)
    assert (await solo.service.submit(MESSAGE, 2, "12", NOW)).status is S.CORRECT


# ------------------------------------------------------------------------------------------ statistics

async def seed(e, day_offsets_and_solvers):
    """Create sent posts on consecutive days ending 19 Oct 2026 and record who solved each."""
    bank = make_bank(*[raw(f"p{i}", ["analysis", "topology", "geometry"][i % 3], "core") for i in range(5)])
    e.service.bank = bank
    posts = []
    for i, solvers in enumerate(day_offsets_and_solvers):
        day = date(2026, 10, 15) + timedelta(days=i)
        post = await e.repo.claim_post(GUILD, day, f"p{i}", CHANNEL, "UTC", NOW, timedelta(minutes=10))
        await e.repo.finish_post(post.id, 1000 + i)
        for user, hints in solvers.items():
            for _ in range(hints):
                await e.repo.use_hint(post.id, user, 3)
            await e.repo.mark_solved(post.id, user, NOW)
        posts.append(post)
    return posts


TODAY_NOON = NOW.replace(hour=12)          # 19 Oct 12:00 UTC: today's problem is still open


async def test_stats_streaks_subjects_and_unaided_solves(env):
    await seed(env, [{1: 0, 2: 1}, {1: 1, 2: 0}, {1: 0}, {1: 0, 2: 0}, {1: 0, 2: 2}])
    s1 = await env.service.stats(GUILD, 1, TODAY_NOON)
    assert (s1.solved, s1.current_streak, s1.best_streak, s1.solved_without_hints, s1.total_posts) == (5, 5, 5, 4, 5)
    assert s1.by_subject == {"Analysis": 2, "Topology": 2, "Geometry": 1}
    s2 = await env.service.stats(GUILD, 2, TODAY_NOON)
    assert (s2.solved, s2.current_streak, s2.best_streak) == (4, 2, 2)                  # missed the third problem
    nobody = await env.service.stats(GUILD, 99, TODAY_NOON)
    assert (nobody.solved, nobody.current_streak, nobody.best_streak, nobody.total_posts) == (0, 0, 0, 5)


async def test_an_open_unsolved_problem_does_not_end_a_streak_but_a_closed_one_does(env):
    await seed(env, [{1: 0}, {1: 0}, {1: 0}, {1: 0}, {}])
    assert (await env.service.stats(GUILD, 1, TODAY_NOON)).current_streak == 4          # today still open
    assert (await env.service.stats(GUILD, 1, TODAY_NOON + timedelta(days=1))).current_streak == 0   # day over, unsolved


async def test_a_day_with_no_post_does_not_break_a_streak(env):
    bank = make_bank(raw("p0"), raw("p1"))
    env.service.bank = bank
    for i, day in enumerate([date(2026, 10, 16), date(2026, 10, 19)]):                  # nothing was posted on the 17th and 18th
        post = await env.repo.claim_post(GUILD, day, f"p{i}", CHANNEL, "UTC", NOW, timedelta(minutes=10))
        await env.repo.finish_post(post.id, 2000 + i)
        await env.repo.mark_solved(post.id, 1, NOW)
    assert (await env.service.stats(GUILD, 1, TODAY_NOON)).current_streak == 2


async def test_the_leaderboard_orders_by_solves_then_streaks_and_ties_share_a_rank(env):
    await seed(env, [{1: 0, 2: 0, 4: 0}, {1: 0, 2: 0, 4: 0}, {1: 0, 4: 0}, {1: 0, 2: 0, 4: 0}, {1: 0, 2: 0, 3: 0, 5: 0}])
    rows = await env.service.leaderboard(GUILD, TODAY_NOON)
    assert [(r.rank, r.user_id) for r in rows] == [(1, 1), (2, 4), (3, 2), (4, 3), (4, 5)]
    assert (rows[0].solved, rows[0].best_streak) == (5, 5)
    assert (rows[1].solved, rows[1].best_streak, rows[1].current_streak) == (4, 4, 4)   # ahead of user 2 on best streak
    assert (rows[2].solved, rows[2].best_streak, rows[2].current_streak) == (4, 2, 2)
    assert len(await env.service.leaderboard(GUILD, TODAY_NOON, limit=2)) == 2
    assert await env.service.leaderboard(777, TODAY_NOON) == []


async def test_servers_have_separate_statistics(env):
    await seed(env, [{1: 0}])
    assert (await env.service.stats(GUILD, 1, TODAY_NOON)).solved == 1
    assert (await env.service.stats(GUILD + 1, 1, TODAY_NOON)).solved == 0


class CountingEngine(InProcessEngine):
    def __init__(self):
        self.calls = 0

    async def run(self, op, **args):
        self.calls += 1
        return await super().run(op, **args)


async def test_after_viewing_the_solution_a_submission_is_refused_without_grading_or_charging_an_attempt(open_db):
    db = await open_db()
    engine = CountingEngine()
    e = make_env(db, make_bank(raw("irr", answer="pi/4")), engine)
    await posted(e)
    await e.service.reveal(MESSAGE, 1, NOW, confirmed=True)
    result = await e.service.submit(MESSAGE, 1, "2*pi/8", NOW)                          # would need the engine to grade
    assert result.status is S.REVEALED and result.attempts == 0
    assert engine.calls == 0
    assert (await e.repo.get_progress(1, 1)).attempts == 0


async def test_a_solved_problem_is_not_graded_again(open_db):
    db = await open_db()
    engine = CountingEngine()
    e = make_env(db, make_bank(raw("irr", answer="pi/4")), engine)
    await posted(e)
    await e.service.submit(MESSAGE, 1, "pi/4", NOW)
    before = engine.calls
    assert (await e.service.submit(MESSAGE, 1, "pi/4", NOW + timedelta(minutes=1))).status is S.ALREADY_SOLVED
    assert engine.calls == before
