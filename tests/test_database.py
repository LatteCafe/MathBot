from database.db import MIGRATIONS_DIR

SHIPPED = sorted(int(f.name.split("_", 1)[0]) for f in MIGRATIONS_DIR.glob("*.sql"))
TABLES = {"schema_migrations", "scheduled_jobs", "guild_settings", "potd_posts", "potd_progress"}


async def table_names(db):
    async with db.conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'") as cur:
        return {r["name"] for r in await cur.fetchall()}


async def test_open_applies_every_shipped_migration_in_order(open_db):
    db = await open_db()
    async with db.conn.execute("SELECT version FROM schema_migrations ORDER BY version") as cur:
        assert [r["version"] for r in await cur.fetchall()] == SHIPPED
    assert TABLES <= await table_names(db)


async def test_migration_numbers_are_unique_and_consecutive():
    assert SHIPPED == list(range(1, len(SHIPPED) + 1))


async def test_reopening_is_idempotent_and_keeps_data(open_db):
    db = await open_db("keep.sqlite3")
    await db.conn.execute("INSERT INTO scheduled_jobs (name, next_run_at) VALUES ('potd', '2026-01-01T00:00:00+00:00')")
    await db.conn.commit()
    await db.close()

    db = await open_db("keep.sqlite3")
    assert await db.migrate() == []          # nothing pending
    async with db.conn.execute("SELECT COUNT(*) AS n FROM schema_migrations") as cur:
        assert (await cur.fetchone())["n"] == len(SHIPPED)
    async with db.conn.execute("SELECT name FROM scheduled_jobs") as cur:
        assert [r["name"] for r in await cur.fetchall()] == ["potd"]


async def test_creates_missing_parent_directory(open_db, tmp_path):
    await open_db("nested/dir/x.sqlite3")
    assert (tmp_path / "nested" / "dir" / "x.sqlite3").exists()


async def test_a_new_migration_file_is_applied_on_next_open(open_db, tmp_path, monkeypatch):
    extra = tmp_path / "migrations"
    extra.mkdir()
    for f in MIGRATIONS_DIR.glob("*.sql"):
        (extra / f.name).write_text(f.read_text())
    (extra / "900_extra.sql").write_text("CREATE TABLE extra (id INTEGER PRIMARY KEY);")
    monkeypatch.setattr("database.db.MIGRATIONS_DIR", extra)

    db = await open_db("with_extra.sqlite3")
    async with db.conn.execute("SELECT version FROM schema_migrations ORDER BY version") as cur:
        assert [r["version"] for r in await cur.fetchall()] == SHIPPED + [900]
    assert "extra" in await table_names(db)


async def test_foreign_keys_are_enforced(open_db):
    """Progress rows must belong to a post: the schema relies on this (and on ON DELETE CASCADE)."""
    db = await open_db()
    try:
        await db.conn.execute("INSERT INTO potd_progress (post_id, user_id) VALUES (999, 1)")
        raised = False
    except Exception:  # noqa: BLE001 - sqlite3.IntegrityError
        raised = True
    assert raised
