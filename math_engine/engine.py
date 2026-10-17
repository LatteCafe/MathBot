"""Async facade used by the Discord cogs. Standard library only (SymPy lives in the worker)."""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from .errors import ComputeFailed, ComputeTimeout, InputError
from .results import MathResult
from .validate import DEFAULT_MAX_LENGTH, check_inputs

log = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
_PASSTHROUGH_ENV = ("PATH", "HOME", "SYSTEMROOT", "LANG", "LC_ALL")


class MathEngine:
    def __init__(self, *, timeout: float = 15.0, memory_limit_mb: int = 512,
                 max_input_length: int = DEFAULT_MAX_LENGTH, max_concurrent: int = 2,
                 python: str | None = None) -> None:
        self.timeout = timeout
        self.memory_limit_mb = memory_limit_mb
        self.max_input_length = max_input_length
        self._python = python or sys.executable
        self._semaphore = asyncio.Semaphore(max_concurrent)

    def _build_env(self) -> dict[str, str]:
        """Minimal environment for the worker. Deliberately excludes DISCORD_TOKEN and other secrets."""
        env = {k: os.environ[k] for k in _PASSTHROUGH_ENV if k in os.environ}
        env["PYTHONPATH"] = str(PROJECT_ROOT)
        env["MATH_MEMORY_LIMIT_MB"] = str(self.memory_limit_mb)
        env["MATH_CPU_LIMIT_SECONDS"] = str(int(self.timeout) + 2)
        return env

    async def run(self, op: str, **args) -> MathResult:
        check_inputs(op, args, self.max_input_length)  # cheap rejection: no process is spawned for bad input
        payload = json.dumps({"op": op, "args": args, "max_input_length": self.max_input_length}).encode()

        async with self._semaphore:
            proc = await asyncio.create_subprocess_exec(
                self._python, "-m", "math_engine.worker",
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                cwd=PROJECT_ROOT, env=self._build_env(),
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(payload), self.timeout)
            except asyncio.TimeoutError:
                raise ComputeTimeout(
                    f"The calculation took longer than {self.timeout:g} seconds and was stopped. "
                    "Try a simpler expression."
                ) from None
            finally:
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()

        if proc.returncode != 0 or not stdout:
            log.error("Math worker exited with code %s: %s", proc.returncode, stderr.decode(errors="replace")[-500:])
            raise ComputeFailed("The calculation stopped unexpectedly (it may have exceeded the memory limit).")
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            log.error("Math worker returned invalid output: %r", stdout[:200])
            raise ComputeFailed("The calculation returned an unreadable result.") from None
        if data["ok"]:
            return MathResult(**data["result"])
        if data["error_type"] == "input":
            raise InputError(data["message"])
        raise ComputeFailed(data["message"])
