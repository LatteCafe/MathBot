"""End-to-end tests of the subprocess sandbox. Each test that spawns a worker takes about a second."""
import sys

import pytest

from math_engine.engine import MathEngine
from math_engine.errors import ComputeFailed, ComputeTimeout, InputError


async def test_runs_calculation_in_subprocess():
    result = await MathEngine().run("simplify", expression="(x^2-1)/(x-1)")
    assert result.text == "x + 1"


async def test_input_errors_from_worker_surface_as_input_error():
    with pytest.raises(InputError, match="several variables"):
        await MathEngine().run("diff", expression="x*y")


async def test_invalid_input_is_rejected_without_spawning_a_process(monkeypatch):
    engine = MathEngine()

    async def boom(*a, **k):
        raise AssertionError("a worker process should not be spawned for invalid input")

    monkeypatch.setattr("asyncio.create_subprocess_exec", boom)
    with pytest.raises(InputError):
        await engine.run("simplify", expression="__import__('os').system('ls')")


async def test_timeout_kills_the_worker():
    with pytest.raises(ComputeTimeout, match="took longer"):
        await MathEngine(timeout=0.05).run("simplify", expression="x + 1")


@pytest.mark.skipif(sys.platform == "win32", reason="memory cap uses POSIX resource limits")
async def test_memory_limit_is_enforced_as_a_clean_failure():
    with pytest.raises(ComputeFailed):
        await MathEngine(memory_limit_mb=20).run("simplify", expression="x + 1")


def test_worker_environment_does_not_contain_secrets(monkeypatch):
    monkeypatch.setenv("DISCORD_TOKEN", "super-secret")
    monkeypatch.setenv("SOME_API_KEY", "also-secret")
    env = MathEngine()._build_env()
    assert "DISCORD_TOKEN" not in env and "SOME_API_KEY" not in env
    assert "super-secret" not in env.values()


async def test_new_operations_work_through_the_subprocess_including_none_arguments():
    engine = MathEngine()
    r = await engine.run("integrate", expression="x^2", variable=None, lower="0", upper="3")
    assert r.text == "9"
    r = await engine.run("integrate", expression="x^2", variable=None, lower=None, upper=None)
    assert r.text == "x^3/3"
    assert (await engine.run("evaluate", expression="sqrt(2)", digits=10)).text == "1.414213562"


async def test_matrix_operation_through_the_subprocess():
    engine = MathEngine()
    assert (await engine.run("matrix", operation="determinant", a="[[1,2],[3,4]]", b=None)).text == "-2"
    assert (await engine.run("matrix", operation="eigenvalues", a="[[2,0],[0,3]]", b=None)).text == "λ = 2, λ = 3"


async def test_invalid_matrix_input_does_not_spawn_a_worker(monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("no worker should be spawned")

    monkeypatch.setattr("asyncio.create_subprocess_exec", boom)
    with pytest.raises(InputError):
        await MathEngine().run("matrix", operation="determinant", a="[[__import__('os')]]", b=None)
