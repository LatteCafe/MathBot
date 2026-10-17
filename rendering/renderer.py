"""Async interface to LaTeX rendering. Standard library only (matplotlib lives in the worker)."""
from __future__ import annotations

import base64
import logging

from math_engine.sandbox import Sandbox

from .parse import DEFAULT_MAX_LENGTH, parse_latex

log = logging.getLogger(__name__)
WARM_UP_TIMEOUT = 180.0


class LatexRenderer:
    def __init__(self, sandbox: Sandbox, *, max_length: int = DEFAULT_MAX_LENGTH,
                 fontsize: float = 20.0, dpi: int = 200) -> None:
        self.sandbox = sandbox
        self.max_length = max_length
        self.fontsize = fontsize
        self.dpi = dpi

    async def render(self, latex: str, *, max_length: int | None = None, timeout: float | None = None) -> bytes:
        """Render LaTeX to PNG bytes. Raises InputError (bad LaTeX), ComputeTimeout or ComputeFailed."""
        limit = max_length or self.max_length
        parse_latex(latex, limit)  # cheap pre-check: bad input never spawns a worker
        data = await self.sandbox.call(
            "rendering.worker",
            {"latex": latex, "max_length": limit, "fontsize": self.fontsize, "dpi": self.dpi},
            timeout=timeout,
        )
        return base64.b64decode(data["png"])

    async def warm_up(self) -> None:
        """Render something tiny so matplotlib builds its font cache before the first real request.

        The first-ever run can be slow (the cache is built from the installed fonts), so it gets a long
        timeout. A normal-length one could kill it before the cache is saved, and then every attempt
        would repeat the same slow build.
        """
        try:
            await self.render(r"x^2", timeout=WARM_UP_TIMEOUT)
            log.info("LaTeX renderer is ready")
        except Exception:  # noqa: BLE001 - a failed warm-up must not stop the bot starting
            log.exception("LaTeX renderer warm-up failed; /latex may not work")
