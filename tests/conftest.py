"""Shared test setup."""
import asyncio

import pytest

from database.db import Database
from math_engine.sandbox import Sandbox


@pytest.fixture(scope="session", autouse=True)
def warm_matplotlib_font_cache():
    """The first matplotlib run on a machine builds a font cache, which can take longer than the normal worker
    timeout. Do it once up front with a generous timeout so individual tests are not flaky on a fresh checkout."""
    payload = {"latex": "x^2", "max_length": 300, "fontsize": 20, "dpi": 200}
    asyncio.run(Sandbox(timeout=180).call("rendering.worker", payload))


@pytest.fixture
async def open_db(tmp_path):
    """Factory for databases that are closed in teardown, so a FAILING test cannot leave an aiosqlite thread running
    (which would keep the whole pytest process alive instead of reporting the failure)."""
    opened = []

    async def factory(name: str = "test.sqlite3") -> Database:
        db = await Database.open(str(tmp_path / name))
        opened.append(db)
        return db

    yield factory
    for db in opened:
        try:
            await db.close()
        except Exception:  # noqa: BLE001 - already closed by the test itself
            pass
