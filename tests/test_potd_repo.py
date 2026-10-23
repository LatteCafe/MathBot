import asyncio
import random
from datetime import date, datetime, timedelta, timezone

import pytest

from database.db import Database
from database.potd_repo import GuildSettings, PotdRepository, from_db, to_db
from services.potd import PotdService, RevealStatus, SubmitStatus
from tests.potd_support import NOW, InProcessEngine, make_bank, raw

DAY = date(2026, 10, 19)
STALE = timedelta(minutes=10)


@pytest.fixture
async def repo(open_db):
    return PotdRepository(await open_db("repo.sqlite3"))


async def claim(repo, day=DAY, guild=1, problem="p1", now=NOW):
    return await repo.claim_post(guild, day, problem, 10, "UTC", now, STALE)


def test_timestamps_round_trip_and_sort_as_text():
    moments = [NOW, NOW + timedelta(microseconds=1), NOW + timedelta(seconds=1), NOW - timedelta(days=400)]
    assert [from_db(to_db(m)) for m in moments] == moments
    assert sorted(moments) == sorted(moments, key=to_db)                       # text order == time order
    assert to_db(datetime(2026, 10, 19, 10, 0, tzinfo=timezone(timedelta(hours=-4)))) == to_db(NOW)


async def test_settings_round_trip_including_unset_channel(repo):
    s = GuildSettings(7, True, 123, 21, 45, "Asia/Kolkata", "challenge", 90)
    await repo.save_settings(s)
    assert await repo.get_settings(7) == s
    await repo.save_settings(s.with_changes(channel_id=None, enabled=False))
    assert (await repo.get_settings(7)).channel_id is None
    assert await repo.enabled_guilds() == []                                      # needs both enabled AND a channel


async def test_enabled_guilds_lists_only_fully_configured_servers(repo):
    await repo.save_settings(GuildSettings(1, True, 11))
    await repo.save_settings(GuildSettings(2, True, None))
    await repo.save_settings(GuildSettings(3, False, 33))
    assert [g.guild_id for g in await repo.enabled_guilds()] == [1]


async def test_database_constraints_reject_nonsense_settings(repo):
    with pytest.raises(Exception):
        await repo.save_settings(GuildSettings(1, True, 1, hour=24))
    with pytest.raises(Exception):
        await repo.save_settings(GuildSettings(1, True, 1, difficulty="trivial"))


async def test_one_post_per_server_per_day(repo):
    first = await claim(repo)
    assert first and first.message_id is None and first.post_date == DAY
    assert await claim(repo) is None                                               # same server, same day
    assert await claim(repo, guild=2) is not None                                  # other server: fine
    assert await claim(repo, day=DAY + timedelta(days=1)) is not None              # other day: fine


async def test_stale_unsent_claims_are_taken_over_but_sent_ones_never(repo):
    first = await claim(repo)
    assert await claim(repo, now=NOW + timedelta(minutes=9, seconds=59), problem="p2") is None
    retaken = await claim(repo, now=NOW + timedelta(minutes=10, seconds=1), problem="p2")
    assert retaken and retaken.id == first.id and retaken.problem_id == "p2"       # same row, new problem
    await repo.finish_post(first.id, 777)
    assert await claim(repo, now=NOW + timedelta(days=3), problem="p3") is None    # sent: never taken over, however old


async def test_finish_lookup_and_delete(repo):
    post = await claim(repo)
    await repo.finish_post(post.id, 4242)
    assert (await repo.get_post_by_message(4242)).id == post.id
    assert await repo.get_post_by_message(1) is None
    await repo.delete_post(post.id)
    assert await repo.get_post_by_message(4242) is None and await repo.get_post_by_date(1, DAY) is None


async def test_history_and_sent_posts(repo):
    a = await claim(repo, day=DAY)
    b = await claim(repo, day=DAY + timedelta(days=1), problem="p2")
    await repo.finish_post(b.id, 2)
    assert sorted(await repo.history(1)) == [("p1", DAY), ("p2", DAY + timedelta(days=1))]
    assert [p.id for p in await repo.sent_posts(1)] == [b.id]                      # unsent claims are not "posts" yet
    await repo.finish_post(a.id, 1)
    assert [p.post_date for p in await repo.sent_posts(1)] == [DAY, DAY + timedelta(days=1)]


async def test_hint_counter_never_exceeds_the_maximum(repo):
    post = await claim(repo)
    assert [await repo.use_hint(post.id, 5, 2) for _ in range(4)] == [1, 2, 2, 2]


async def test_attempts_and_timestamps(repo):
    post = await claim(repo)
    assert await repo.record_attempt(post.id, 5, NOW) == 1
    assert await repo.record_attempt(post.id, 5, NOW + timedelta(seconds=30)) == 2
    progress = await repo.get_progress(post.id, 5)
    assert progress.attempts == 2 and progress.last_attempt_at == NOW + timedelta(seconds=30)
    assert (await repo.get_progress(post.id, 6)).attempts == 0                    # other users unaffected


async def test_a_solve_is_recorded_once_and_never_after_the_solution_was_viewed(repo):
    post = await claim(repo)
    assert await repo.mark_solved(post.id, 1, NOW) is True
    assert await repo.mark_solved(post.id, 1, NOW + timedelta(minutes=1)) is False
    assert (await repo.get_progress(post.id, 1)).solved_at == NOW                  # the first solve time is kept
    await repo.mark_revealed(post.id, 2, NOW)
    assert await repo.mark_solved(post.id, 2, NOW + timedelta(minutes=1)) is False
    assert await repo.solved_post_ids(1, 2) == set()


async def test_the_first_reveal_time_is_kept(repo):
    post = await claim(repo)
    await repo.mark_revealed(post.id, 1, NOW)
    await repo.mark_revealed(post.id, 1, NOW + timedelta(hours=1))
    assert (await repo.get_progress(post.id, 1)).revealed_at == NOW


async def test_deleting_a_post_deletes_its_progress(repo):
    post = await claim(repo)
    await repo.finish_post(post.id, 1)
    await repo.mark_solved(post.id, 1, NOW)
    await repo.delete_post(post.id)
    assert await repo.solved_rows(1) == []
    async with repo.conn.execute("SELECT COUNT(*) AS n FROM potd_progress") as cur:
        assert (await cur.fetchone())["n"] == 0


async def test_everything_survives_a_restart(open_db):
    db = await open_db("restart.sqlite3")
    repo = PotdRepository(db)
    await repo.save_settings(GuildSettings(1, True, 11, 8, 15, "Europe/London", "advanced", 45))
    post = await claim(repo)
    await repo.finish_post(post.id, 99)
    await repo.use_hint(post.id, 5, 3)
    await repo.mark_solved(post.id, 5, NOW)
    await db.close()                                                              # "shut the bot down"

    reopened_db = await open_db("restart.sqlite3")                                # "start it again"
    reopened = PotdRepository(reopened_db)
    assert (await reopened.get_settings(1)).timezone == "Europe/London"
    assert (await reopened.get_post_by_message(99)).problem_id == "p1"
    progress = await reopened.get_progress(post.id, 5)
    assert progress.hints_used == 1 and progress.solved_at == NOW
    assert await claim(reopened) is None                                           # and it still will not double-post


# ------------------------------------------------------------------------------------------ a race the SQL guard exists for

class RevealDuringGrading:
    """An engine that, while it is 'grading', lets the user click 'Show solution anyway' in another interaction."""

    def __init__(self):
        self.service = None

    async def run(self, op, **args):
        await self.service.reveal(555, 1, NOW, confirmed=True)
        return await InProcessEngine().run(op, **args)


async def test_revealing_while_an_answer_is_being_graded_never_gives_credit_or_a_false_Correct(open_db):
    db = await open_db()
    engine = RevealDuringGrading()
    service = PotdService(PotdRepository(db), make_bank(raw("irr", answer="pi/4")), engine, random.Random(1))
    engine.service = service
    await service.update_settings(100, enabled=True, channel_id=1, hour=9, timezone="America/Toronto")
    (item,) = await service.due_posts(NOW)
    await service.complete_post(item.post.id, 555)

    result = await service.submit(555, 1, "2*pi/8", NOW)          # the answer is right, but the solution was revealed meanwhile
    assert result.status is SubmitStatus.REVEALED
    assert await service.repo.solved_post_ids(100, 1) == set()
    assert (await service.reveal(555, 1, NOW)).status is RevealStatus.SHOWN


async def test_two_simultaneous_correct_submissions_credit_exactly_once(open_db):
    db = await open_db()
    service = PotdService(PotdRepository(db), make_bank(raw("irr", answer="pi/4")), InProcessEngine(), random.Random(1))
    await service.update_settings(100, enabled=True, channel_id=1, hour=9, timezone="America/Toronto")
    (item,) = await service.due_posts(NOW)
    await service.complete_post(item.post.id, 555)
    results = await asyncio.gather(*[service.submit(555, 1, "pi/4", NOW) for _ in range(4)])
    statuses = sorted(r.status.value for r in results)
    assert statuses.count("correct") == 1 and set(statuses) <= {"correct", "already_solved"}
    assert await service.repo.solved_post_ids(100, 1) == {item.post.id}
