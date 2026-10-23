import dataclasses
from pathlib import Path

import pytest
import yaml

from cogs.potd import problem_embed, solution_embed
from rendering.draw import render_png
from rendering.parse import parse_latex
from services.problem_bank import (DEFAULT_CHOICE_ATTEMPTS, LEVELS, SUBJECTS, ProblemBankError, load_bank,
                                   parse_problems)
from tests.potd_support import raw

BANK_PATH = Path(__file__).resolve().parent.parent / "data" / "problems.yaml"
BANK = load_bank(BANK_PATH)


# ------------------------------------------------------------------------------------------ the real bank

def test_the_shipped_bank_is_large_balanced_and_covers_every_subject():
    assert len(BANK) >= 40
    for level in LEVELS:
        assert len(BANK.by_level(level)) >= 5, level
    assert {p.subject for p in BANK} == set(SUBJECTS)
    assert not any(p.level not in LEVELS for p in BANK)


def test_every_problem_has_hints_a_solution_and_a_unique_id():
    assert len({p.id for p in BANK}) == len(BANK)
    for p in BANK:
        assert 1 <= len(p.hints) <= 3 and len(p.solution) > 80, p.id


@pytest.mark.parametrize("problem", [p for p in BANK if p.display], ids=lambda p: p.id)
def test_every_display_formula_typesets(problem):
    render_png(parse_latex(problem.display, 1000))


@pytest.mark.parametrize("problem", list(BANK), ids=lambda p: p.id)
def test_every_problem_fits_discords_limits_and_does_not_leak(problem):
    from datetime import date
    embed = problem_embed(problem, date(2026, 10, 19), image=bool(problem.display))
    assert len(embed) <= 6000 and len(embed.description) <= 4096 and len(embed.title) <= 256
    posted = " ".join([embed.title or "", embed.description or "", embed.footer.text or "", embed.author.name or ""]
                      + [f"{f.name} {f.value}" for f in embed.fields])           # EVERYTHING visible in the public post
    assert problem.solution[:60] not in posted
    assert all(hint not in posted for hint in problem.hints)
    assert len(solution_embed(problem).description) <= 4096


def test_choice_problems_list_their_options_and_default_to_limited_attempts():
    choice = [p for p in BANK if p.answer_type == "choice"]
    assert choice
    for p in choice:
        assert p.max_attempts == DEFAULT_CHOICE_ATTEMPTS
        assert all(f"**{letter}.**" in p.statement_text for letter in p.option_letters)
        assert p.answer in p.option_letters


def test_no_problem_is_trivially_short_or_school_level_in_the_core_tier():
    """A cheap guard on the brief ('math majors, no simple polynomial questions')."""
    banned = ("quadratic formula", "solve for x", "factor the polynomial", "expand (x")
    for p in BANK:
        text = (p.statement + (p.display or "")).lower()
        assert not any(b in text for b in banned), p.id


# ------------------------------------------------------------------------------------------ validation

def errors_for(*problems) -> str:
    with pytest.raises(ProblemBankError) as info:
        parse_problems(list(problems))
    return str(info.value)


def test_a_valid_problem_parses_with_defaults():
    (p,) = parse_problems([raw()])
    assert p.answer == "12" and p.answer_display == "12" and p.max_attempts is None and p.display is None


def test_integer_answers_are_accepted_but_floats_and_bools_are_not():
    assert parse_problems([raw(answer=504)])[0].answer == "504"
    assert "answer must be text or an integer" in errors_for(raw(answer=0.5))
    assert "answer must be text or an integer" in errors_for(raw(answer=True))


@pytest.mark.parametrize("override,fragment", [
    ({"id": "Bad_ID"}, "id must be lowercase"),
    ({"subject": "alchemy"}, "subject must be one of"),
    ({"level": "easy"}, "level must be one of"),
    ({"answer_type": "essay"}, "answer_type must be one of"),
    ({"answer": "__import__('os')"}, "not valid calculator syntax"),
    ({"answer": "x y z"}, "not valid calculator syntax"),
    ({"hints": ["a", "b", "c", "d"]}, "at most 3"),
    ({"hints": ["ok", ""]}, "non-empty"),
    ({"title": "t" * 81}, "title is too long"),
    ({"statement": "s" * 1501}, "statement is too long"),
    ({"solution": "s" * 3001}, "solution is too long"),
    ({"display": "d" * 1001}, "display is too long"),
    ({"max_attempts": 0}, "max_attempts"),
    ({"options": ["a", "b"]}, "only for choice"),
    ({"colour": "red"}, "unknown field 'colour'"),
])
def test_invalid_problems_are_rejected_with_a_specific_message(override, fragment):
    assert fragment in errors_for(raw(**override))


@pytest.mark.parametrize("missing", ["id", "subject", "level", "title", "statement", "answer", "solution"])
def test_missing_required_fields_are_reported(missing):
    data = raw()
    del data[missing]
    assert f"missing required field {missing!r}" in errors_for(data)


def test_choice_problem_rules():
    ok = raw(answer_type="choice", answer="b", options=["x", "y", "z"])
    (p,) = parse_problems([ok])
    assert p.answer == "B" and p.answer_display == "B. y" and p.max_attempts == 2
    assert "needs 2 to 5" in errors_for(raw(answer_type="choice", answer="A", options=["only one"]))
    assert "option letters" in errors_for(raw(answer_type="choice", answer="D", options=["x", "y", "z"]))


def test_duplicate_ids_and_multiple_errors_are_all_reported_together():
    message = errors_for(raw(id="same"), raw(id="same"), raw(id="other", level="easy"), raw(id="third", subject="x"))
    assert "same: duplicate id" in message and "other: level must be" in message and "third: subject must be" in message


def test_the_loader_reads_utf8_and_reports_file_problems(tmp_path):
    good = tmp_path / "bank.yaml"
    good.write_text(yaml.safe_dump({"problems": [raw(statement="Évaluer ∫₀¹ ln x dx = −1 (ℝ, ℤ, π)")]},
                                    allow_unicode=True), encoding="utf-8")
    assert "∫₀¹" in load_bank(good).get("p1").statement
    with pytest.raises(ProblemBankError, match="not found"):
        load_bank(tmp_path / "missing.yaml")
    (tmp_path / "bad.yaml").write_text("problems: [unclosed", encoding="utf-8")
    with pytest.raises(ProblemBankError, match="not valid YAML"):
        load_bank(tmp_path / "bad.yaml")
    (tmp_path / "empty.yaml").write_text("problems: []", encoding="utf-8")
    with pytest.raises(ProblemBankError, match="non-empty"):
        load_bank(tmp_path / "empty.yaml")


def test_problems_are_immutable():
    (p,) = parse_problems([raw()])
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.answer = "13"
