"""The curated problem bank: loading and validation. Standard library + PyYAML only; no Discord imports."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

from math_engine.errors import InputError
from math_engine.validate import validate_expression

SUBJECTS = {
    "analysis": "Analysis", "abstract_algebra": "Abstract Algebra", "linear_algebra": "Linear Algebra",
    "number_theory": "Number Theory", "combinatorics": "Combinatorics", "probability": "Probability",
    "complex_analysis": "Complex Analysis", "topology": "Topology", "geometry": "Geometry",
}
LEVELS = {"core": "Core", "advanced": "Advanced", "challenge": "Challenge"}
LEVEL_BLURBS = {
    "core": "upper-division course material",
    "advanced": "competition-style; needs a real idea",
    "challenge": "hard: Putnam-hard or graduate flavoured",
}
ANSWER_TYPES = ("value", "choice")
DEFAULT_CHOICE_ATTEMPTS = 2
DEFAULT_ANSWER_FORMAT = "Exact answer, e.g. 3/8, pi/4 or sqrt(2) - 1"

MAX_TITLE, MAX_STATEMENT, MAX_DISPLAY, MAX_SOLUTION, MAX_HINT, MAX_HINTS = 80, 1500, 1000, 3000, 600, 3
_ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
_KNOWN_KEYS = {"id", "subject", "level", "title", "statement", "display", "answer_type", "answer", "answer_display",
               "answer_format", "options", "max_attempts", "hints", "solution"}
_REQUIRED_KEYS = ("id", "subject", "level", "title", "statement", "answer_type", "answer", "solution")


class ProblemBankError(Exception):
    """The problem bank file is missing or invalid. The message lists every problem found."""


@dataclass(frozen=True)
class Problem:
    id: str
    subject: str
    level: str
    title: str
    statement: str
    display: str | None
    answer_type: str
    answer: str
    answer_display: str
    answer_format: str
    options: tuple[str, ...]
    max_attempts: int | None
    hints: tuple[str, ...]
    solution: str

    @property
    def subject_label(self) -> str:
        return SUBJECTS[self.subject]

    @property
    def level_label(self) -> str:
        return LEVELS[self.level]

    @property
    def statement_text(self) -> str:
        """The statement, followed by the lettered options for multiple-choice problems."""
        if not self.options:
            return self.statement
        lines = [f"**{chr(65 + i)}.** {text}" for i, text in enumerate(self.options)]
        return self.statement + "\n\n" + "\n".join(lines)

    @property
    def option_letters(self) -> str:
        return "".join(chr(65 + i) for i in range(len(self.options)))


class ProblemBank:
    def __init__(self, problems: list[Problem]) -> None:
        self._problems = list(problems)
        self._by_id = {p.id: p for p in self._problems}

    def get(self, problem_id: str) -> Problem | None:
        return self._by_id.get(problem_id)

    def __len__(self) -> int:
        return len(self._problems)

    def __iter__(self):
        return iter(self._problems)

    def by_level(self, level: str) -> list[Problem]:
        return [p for p in self._problems if p.level == level]


def load_bank(path: str | Path) -> ProblemBank:
    path = Path(path)
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))  # utf-8 explicitly: Windows defaults to cp1252
    except FileNotFoundError:
        raise ProblemBankError(f"Problem bank not found: {path}") from None
    except yaml.YAMLError as exc:
        raise ProblemBankError(f"Problem bank {path} is not valid YAML: {exc}") from None
    if not isinstance(raw, dict) or not isinstance(raw.get("problems"), list) or not raw["problems"]:
        raise ProblemBankError(f"{path} must contain a non-empty 'problems:' list.")
    return ProblemBank(parse_problems(raw["problems"]))


def parse_problems(raw_problems: list) -> list[Problem]:
    errors: list[str] = []
    problems: list[Problem] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_problems, start=1):
        label = raw.get("id", f"#{index}") if isinstance(raw, dict) else f"#{index}"
        problem_errors: list[str] = []
        problem = _parse_one(raw, problem_errors)
        if problem is not None and problem.id in seen:
            problem_errors.append("duplicate id")
        if problem is not None:
            seen.add(problem.id)
        errors += [f"{label}: {e}" for e in problem_errors]
        if problem is not None and not problem_errors:
            problems.append(problem)
    if errors:
        raise ProblemBankError("Problem bank has errors:\n  " + "\n  ".join(errors))
    return problems


def _parse_one(raw, errors: list[str]) -> Problem | None:
    if not isinstance(raw, dict):
        errors.append("each problem must be a mapping")
        return None
    for key in raw.keys() - _KNOWN_KEYS:
        errors.append(f"unknown field {key!r}")
    for key in _REQUIRED_KEYS:
        if raw.get(key) in (None, ""):
            errors.append(f"missing required field {key!r}")
    if errors:
        return None

    def text(key: str, limit: int, required: bool = True) -> str | None:
        value = raw.get(key)
        if value is None:
            return None
        if not isinstance(value, str) or (required and not value.strip()):
            errors.append(f"{key} must be non-empty text")
            return None
        if len(value) > limit:
            errors.append(f"{key} is too long ({len(value)} characters; the limit is {limit})")
        return value.strip()

    problem_id = str(raw["id"])
    if not _ID_RE.match(problem_id) or len(problem_id) > 60:
        errors.append("id must be lowercase letters, digits and hyphens (at most 60 characters)")
    if raw["subject"] not in SUBJECTS:
        errors.append(f"subject must be one of {', '.join(SUBJECTS)}")
    if raw["level"] not in LEVELS:
        errors.append(f"level must be one of {', '.join(LEVELS)}")
    title, statement = text("title", MAX_TITLE), text("statement", MAX_STATEMENT)
    display = text("display", MAX_DISPLAY, required=False)
    solution = text("solution", MAX_SOLUTION)
    fmt = text("answer_format", 100, required=False)

    hints = raw.get("hints") or []
    if not isinstance(hints, list) or len(hints) > MAX_HINTS or not all(isinstance(h, str) and h.strip() for h in hints):
        errors.append(f"hints must be a list of at most {MAX_HINTS} non-empty strings")
        hints = []
    elif any(len(h) > MAX_HINT for h in hints):
        errors.append(f"each hint must be at most {MAX_HINT} characters")

    answer_type = raw["answer_type"]
    if answer_type not in ANSWER_TYPES:
        errors.append(f"answer_type must be one of {', '.join(ANSWER_TYPES)}")
    options = raw.get("options") or []
    answer = raw["answer"]
    if isinstance(answer, bool) or not isinstance(answer, (str, int)):
        errors.append("answer must be text or an integer (quote it if it is a formula)")
        answer = ""
    answer = str(answer).strip()
    answer_display = text("answer_display", 200, required=False)

    if answer_type == "choice":
        if not isinstance(options, list) or not 2 <= len(options) <= 5 or not all(isinstance(o, str) and o.strip() for o in options):
            errors.append("a choice problem needs 2 to 5 non-empty `options`")
            options = []
        elif answer.upper() not in [chr(65 + i) for i in range(len(options))]:
            errors.append(f"answer must be one of the option letters {''.join(chr(65 + i) for i in range(len(options)))}")
        else:
            answer = answer.upper()
            answer_display = answer_display or f"{answer}. {options[ord(answer) - 65]}"
    elif answer_type == "value":
        if options:
            errors.append("`options` is only for choice problems")
        try:
            validate_expression(answer)
        except InputError as exc:
            errors.append(f"answer {answer!r} is not valid calculator syntax: {exc}")

    attempts = raw.get("max_attempts")
    if attempts is not None and (isinstance(attempts, bool) or not isinstance(attempts, int) or attempts < 1):
        errors.append("max_attempts must be a positive integer")
        attempts = None
    if attempts is None and answer_type == "choice":
        attempts = DEFAULT_CHOICE_ATTEMPTS

    if errors:
        return None
    return Problem(
        id=problem_id, subject=raw["subject"], level=raw["level"], title=title, statement=statement, display=display,
        answer_type=answer_type, answer=answer, answer_display=answer_display or answer,
        answer_format=fmt or DEFAULT_ANSWER_FORMAT, options=tuple(o.strip() for o in options),
        max_attempts=attempts, hints=tuple(h.strip() for h in hints), solution=solution,
    )
