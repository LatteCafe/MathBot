import aiosqlite

from database.db import MIGRATIONS_DIR, Database


async def test_open_applies_migrations(tmp_path):
    db = await Database.open(str(tmp_path / "test.sqlite3"))
    async with db.conn.execute("SELECT version FROM schema_migrations") as cur:
        versions = [r["version"] for r in await cur.fetchall()]
    assert versions == [1]
    async with db.conn.execute("SELECT name FROM sqlite_master WHERE name='scheduled_jobs'") as cur:
        assert await cur.fetchone() is not None
    await db.close()


async def test_reopening_is_idempotent_and_keeps_data(tmp_path):
    path = str(tmp_path / "test.sqlite3")
    db = await Database.open(path)
    await db.conn.execute("INSERT INTO scheduled_jobs (name, next_run_at) VALUES ('potd', '2026-01-01T00:00:00+00:00')")
    await db.conn.commit()
    await db.close()

    db = await Database.open(path)
    assert await db.migrate() == []          # nothing pending
    async with db.conn.execute("SELECT COUNT(*) AS n FROM schema_migrations") as cur:
        assert (await cur.fetchone())["n"] == 1
    async with db.conn.execute("SELECT name FROM scheduled_jobs") as cur:
        assert [r["name"] for r in await cur.fetchall()] == ["potd"]
    await db.close()


async def test_creates_missing_parent_directory(tmp_path):
    db = await Database.open(str(tmp_path / "nested" / "dir" / "x.sqlite3"))
    await db.close()
    assert (tmp_path / "nested" / "dir" / "x.sqlite3").exists()


async def test_new_migration_file_is_applied_on_next_open(tmp_path, monkeypatch):
    extra = tmp_path / "migrations"
    extra.mkdir()
    for f in MIGRATIONS_DIR.glob("*.sql"):
        (extra / f.name).write_text(f.read_text())
    (extra / "002_extra.sql").write_text("CREATE TABLE extra (id INTEGER PRIMARY KEY);")
    monkeypatch.setattr("database.db.MIGRATIONS_DIR", extra)

    db = await Database.open(str(tmp_path / "t.sqlite3"))
    async with db.conn.execute("SELECT version FROM schema_migrations ORDER BY version") as cur:
        assert [r["version"] for r in await cur.fetchall()] == [1, 2]
    await db.close()
