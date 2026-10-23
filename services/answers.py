"""Grading submitted answers. Never reveals the expected answer."""
from __future__ import annotations

import enum
import re
from dataclasses import dataclass
from fractions import Fraction

from math_engine.errors import InputError
from math_engine.validate import validate_expression

from .problem_bank import Problem

_RATIONAL = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)(/\d+)?$")
_CHOICE = re.compile(r"^\(?([A-Za-z])\)?[.)]?$")


class Verdict(enum.Enum):
    CORRECT = "correct"
    INCORRECT = "incorrect"
    INVALID = "invalid"        # could not be understood: does not count as an attempt


@dataclass(frozen=True)
class AnswerCheck:
    verdict: Verdict
    message: str | None = None   # shown to the user for INVALID results


def _rational(text: str) -> Fraction | None:
    """Exact value of a plain integer, decimal or fraction, else None. (No engine needed for these.)"""
    s = text.replace(" ", "")
    if not _RATIONAL.match(s):
        return None
    try:
        return Fraction(s)
    except (ValueError, ZeroDivisionError):
        return None


async def check_answer(problem: Problem, submitted: str, engine) -> AnswerCheck:
    """Grade `submitted`. `engine` is a MathEngine; it may raise ComputeTimeout/ComputeFailed (callers handle those)."""
    text = (submitted or "").strip()
    if not text:
        return AnswerCheck(Verdict.INVALID, "Please type an answer.")

    if problem.answer_type == "choice":
        match = _CHOICE.match(text)
        letters = problem.option_letters
        if not match or match.group(1).upper() not in letters:
            return AnswerCheck(Verdict.INVALID, f"Answer with one of the letters {', '.join(letters)}.")
        return AnswerCheck(Verdict.CORRECT if match.group(1).upper() == problem.answer else Verdict.INCORRECT)

    try:
        validate_expression(text)
    except InputError as exc:
        return AnswerCheck(Verdict.INVALID, str(exc))

    expected, given = _rational(problem.answer), _rational(text)
    if expected is not None and given is not None:        # plain numbers: compare exactly, without a worker process
        return AnswerCheck(Verdict.CORRECT if expected == given else Verdict.INCORRECT)

    try:
        result = await engine.run("equivalent", submitted=text, expected=problem.answer)
    except InputError as exc:       # e.g. "1/0": syntactically fine, but undefined
        return AnswerCheck(Verdict.INVALID, str(exc))
    return AnswerCheck(Verdict.CORRECT if result.text == "equal" else Verdict.INCORRECT)
