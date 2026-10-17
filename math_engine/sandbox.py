"""Run work in a short-lived worker process with a timeout, memory cap and minimal environment.

Used for both SymPy calculations and LaTeX rendering. A worker is ``python -m <module>``: it reads one
JSON request on stdin and writes one JSON reply on stdout, either
``{"ok": true, "result": ...}`` or ``{"ok": false, "error_type": "input"|"internal", "message": ...}``.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

from .errors import ComputeFailed, ComputeTimeout, InputError

log = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
# Harmless variables the worker needs to start (matplotlib needs a home/cache dir on Windows too).
# Everything else, including DISCORD_TOKEN, is deliberately NOT passed on.
_PASSTHROUGH_ENV = ("PATH", "HOME", "USERPROFILE", "APPDATA", "LOCALAPPDATA", "TEMP", "TMP",
                    "SYSTEMROOT", "LANG", "LC_ALL")
MPL_CACHE_DIR = PROJECT_ROOT / "data" / ".cache" / "matplotlib"


class Sandbox:
    def __init__(self, *, timeout: float = 15.0, memory_limit_mb: int = 512, max_concurrent: int = 2,
                 python: str | None = None) -> None:
        self.timeout = timeout
        self.memory_limit_mb = memory_limit_mb
        self._python = python or sys.executable
        self._semaphore = asyncio.Semaphore(max_concurrent)  # caps simultaneous workers (protects small servers)

    def _build_env(self, timeout: float | None = None) -> dict[str, str]:
        env = {k: os.environ[k] for k in _PASSTHROUGH_ENV if k in os.environ}
        env["PYTHONPATH"] = str(PROJECT_ROOT)
        env["MATH_MEMORY_LIMIT_MB"] = str(self.memory_limit_mb)
        env["MATH_CPU_LIMIT_SECONDS"] = str(int(timeout or self.timeout) + 2)
        env["MPLCONFIGDIR"] = str(MPL_CACHE_DIR)  # stable font cache, so rendering isn't slow every time
        return env

    async def call(self, module: str, payload: dict, *, timeout: float | None = None):
        """Run ``python -m module`` with ``payload``. Returns the worker's ``result`` or raises a MathError.

        ``timeout`` overrides the default for this call (used for the one-off font-cache warm-up).
        """
        timeout = timeout or self.timeout
        MPL_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        async with self._semaphore:
            proc = await asyncio.create_subprocess_exec(
                self._python, "-m", module,
                stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
                cwd=PROJECT_ROOT, env=self._build_env(timeout),
            )
            try:
                stdout, stderr = await asyncio.wait_for(proc.communicate(json.dumps(payload).encode()), timeout)
            except asyncio.TimeoutError:
                raise ComputeTimeout(
                    f"That took longer than {timeout:g} seconds and was stopped. Try something simpler."
                ) from None
            finally:
                if proc.returncode is None:
                    proc.kill()
                    await proc.wait()

        if proc.returncode != 0 or not stdout:
            log.error("Worker %s exited with code %s: %s", module, proc.returncode,
                      stderr.decode(errors="replace")[-500:])
            raise ComputeFailed("The worker process stopped unexpectedly (it may have exceeded the memory limit).")
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError:
            log.error("Worker %s returned invalid output: %r", module, stdout[:200])
            raise ComputeFailed("The worker process returned an unreadable result.") from None
        if data["ok"]:
            return data["result"]
        if data["error_type"] == "input":
            raise InputError(data["message"])
        raise ComputeFailed(data["message"])
