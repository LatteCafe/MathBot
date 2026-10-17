"""Async facade used by the Discord cogs. Standard library only (SymPy lives in the worker)."""
from __future__ import annotations

from .results import MathResult
from .sandbox import Sandbox
from .validate import DEFAULT_MAX_LENGTH, check_inputs


class MathEngine:
    def __init__(self, *, sandbox: Sandbox | None = None, timeout: float = 15.0, memory_limit_mb: int = 512,
                 max_input_length: int = DEFAULT_MAX_LENGTH, max_concurrent: int = 2) -> None:
        # Pass a shared Sandbox so calculations and rendering draw from one pool of worker slots.
        self.sandbox = sandbox or Sandbox(timeout=timeout, memory_limit_mb=memory_limit_mb,
                                          max_concurrent=max_concurrent)
        self.max_input_length = max_input_length

    @property
    def timeout(self) -> float:
        return self.sandbox.timeout

    def _build_env(self) -> dict[str, str]:
        return self.sandbox._build_env()

    async def run(self, op: str, **args) -> MathResult:
        check_inputs(op, args, self.max_input_length)  # cheap rejection: no process is spawned for bad input
        data = await self.sandbox.call(
            "math_engine.worker", {"op": op, "args": args, "max_input_length": self.max_input_length}
        )
        return MathResult(**data)
