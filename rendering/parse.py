"""Parse and validate user LaTeX into drawable segments. Standard library only.

matplotlib's math renderer handles ordinary notation (fractions, integrals, sums, limits, Greek, ...) but
not environments such as ``\\begin{pmatrix}``. So the input is split into plain-math segments and matrix
segments; matplotlib renders the math, and draw.py lays matrices out itself.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from math_engine.errors import InputError

DEFAULT_MAX_LENGTH = 300
MAX_SEGMENTS = 20
MAX_MATRIX_DIM = 10
# environment name -> bracket style
MATRIX_KINDS = {"matrix": "none", "pmatrix": "paren", "bmatrix": "bracket", "vmatrix": "bar"}

_BEGIN = re.compile(r"\\begin\{([^}]*)\}")


@dataclass(frozen=True)
class MathSegment:
    text: str


@dataclass(frozen=True)
class MatrixSegment:
    style: str                    # "none" | "paren" | "bracket" | "bar"
    rows: tuple[tuple[str, ...], ...]


def parse_latex(text: str, max_length: int = DEFAULT_MAX_LENGTH) -> list:
    if not isinstance(text, str) or not text.strip():
        raise InputError("The LaTeX expression is empty.")
    if len(text) > max_length:
        raise InputError(f"The expression is too long ({len(text)} characters; the limit is {max_length}).")
    s = " ".join(text.split())  # newlines/tabs -> spaces
    if any(not c.isprintable() for c in s):
        raise InputError("The expression contains unprintable characters.")
    s = _strip_delimiters(s)
    if "$" in s:
        raise InputError("Remove the $ signs: write just the math, e.g. \\frac{a}{b}.")

    segments: list = []
    pos = 0
    while True:
        m = _BEGIN.search(s, pos)
        if not m:
            break
        _add_math(segments, s[pos:m.start()])
        env = m.group(1)
        if env not in MATRIX_KINDS:
            raise InputError(
                f"The environment '{env}' is not supported. Supported: {', '.join(sorted(MATRIX_KINDS))}."
            )
        end_tag = f"\\end{{{env}}}"
        end = s.find(end_tag, m.end())
        if end == -1:
            raise InputError(f"Missing {end_tag}.")
        body = s[m.end():end]
        if "\\begin" in body:
            raise InputError("Nested matrices and environments are not supported.")
        segments.append(_parse_matrix(env, body))
        pos = end + len(end_tag)
    _add_math(segments, s[pos:])

    if "\\end{" in "".join(seg.text for seg in segments if isinstance(seg, MathSegment)):
        raise InputError("Found \\end{...} without a matching \\begin{...}.")
    if not segments:
        raise InputError("The LaTeX expression is empty.")
    if len(segments) > MAX_SEGMENTS:
        raise InputError("The expression has too many parts.")
    return segments


def _strip_delimiters(s: str) -> str:
    s = s.strip()
    for open_, close in (("$$", "$$"), ("$", "$"), ("\\[", "\\]"), ("\\(", "\\)")):
        if len(s) >= len(open_) + len(close) and s.startswith(open_) and s.endswith(close):
            return s[len(open_):len(s) - len(close)].strip()
    return s


def _add_math(segments: list, text: str) -> None:
    text = text.strip()
    if text:
        segments.append(MathSegment(text))


def _parse_matrix(env: str, body: str) -> MatrixSegment:
    rows = [[cell.strip() for cell in row.split("&")] for row in re.split(r"\\\\", body)]
    if rows and all(c == "" for c in rows[-1]) and len(rows) > 1:
        rows.pop()  # a trailing \\ before \end{...} does not start a new row
    width = max(len(r) for r in rows)
    if width > MAX_MATRIX_DIM or len(rows) > MAX_MATRIX_DIM:
        raise InputError(f"Matrices larger than {MAX_MATRIX_DIM}x{MAX_MATRIX_DIM} are not supported.")
    if all(c == "" for r in rows for c in r):
        raise InputError("The matrix is empty.")
    rows = [r + [""] * (width - len(r)) for r in rows]  # ragged rows are padded, as in LaTeX
    return MatrixSegment(MATRIX_KINDS[env], tuple(tuple(r) for r in rows))
