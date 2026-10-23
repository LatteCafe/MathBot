"""Result type shared by the worker process and the bot (standard library only)."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class MathResult:
    text: str                       # human-readable exact result
    latex: str | None = None        # LaTeX for the exact result (used for rendering in Phase 2)
    approximation: str | None = None  # decimal approximation, only when it adds information
    established: bool = True        # False when the result could NOT be established
    note: str | None = None         # extra context, e.g. "solutions over the real numbers"
    approximate_only: bool = False  # True when `text` is itself a decimal approximation (e.g. /evaluate)
    summary: str | None = None      # short description of a very large result, e.g. "integer with 2,997 digits ..."
    truncated: bool = False         # True when `text` is incomplete because the result exceeded the hard size limit
