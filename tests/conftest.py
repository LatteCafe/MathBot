"""Shared test setup."""
import asyncio

import pytest

from math_engine.sandbox import Sandbox


@pytest.fixture(scope="session", autouse=True)
def warm_matplotlib_font_cache():
    """The first matplotlib run on a machine builds a font cache, which can take longer than the normal worker
    timeout. Do it once up front with a generous timeout so individual tests are not flaky on a fresh checkout."""
    payload = {"latex": "x^2", "max_length": 300, "fontsize": 20, "dpi": 200}
    asyncio.run(Sandbox(timeout=180).call("rendering.worker", payload))
