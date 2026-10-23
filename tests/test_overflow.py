"""Results too large to show: recognised, summarised, attached as a file, and never a crash."""
import math
import sys

import pytest

from cogs.calc import Calc
from cogs.formatting import (INLINE_RESULT_CHARS, MAX_MESSAGE, RESULT_FILENAME, attachment_text, format_result,
                             is_overflow)
from math_engine import operations
from math_engine.engine import MathEngine
from math_engine.results import MathResult
from tests.potd_support import FakeInteraction, InProcessEngine


def run(op, **args):
    return operations.run(op, args)


# ------------------------------------------------------------------------------------------ the engine

def test_a_huge_power_is_summarised_with_correct_figures():
    r = run("evaluate", expression="999^999")
    exact = 999**999
    assert len(r.text) == len(str(exact)) == 2997 and r.text == str(exact)
    assert "2,997 digits" in r.summary
    assert f"ending in …{exact % 10**8:08d}" in r.summary
    mantissa = 10 ** (math.log10(exact // 10**2900) - (len(str(exact // 10**2900)) - 1))      # leading digits, via float
    assert r.summary.split("about ")[1].startswith(f"{mantissa:.2f}"[:3]) and "e+2996" in r.summary
    assert not r.truncated and r.latex is None


def test_integers_past_pythons_4300_digit_print_limit_no_longer_crash():
    """Regression: this used to fail with 'The calculation failed (ValueError)'."""
    r = run("evaluate", expression="10^999*10^999*10^999*10^999*10^999")
    assert r.text == "1" + "0" * 4995 and "4,996 digits" in r.summary and not r.truncated


def test_summaries_appear_only_when_they_help():
    assert run("evaluate", expression="7^20").summary is None                          # 17 digits: just show it
    assert run("evaluate", expression="7^100").summary.startswith("integer with 85 digits")   # fits inline, still summarised
    assert run("evaluate", expression="2^1000-1").summary.startswith("integer with 302 digits")
    assert run("simplify", expression="x + 1").summary is None


def test_negative_and_rational_overflow():
    assert run("evaluate", expression="-999^999").summary.startswith("negative integer with 2,997 digits")
    r = run("simplify", expression="1/999^999")
    assert r.summary == "fraction whose numerator has 1 digits and denominator 2,997 digits"


def test_a_huge_sum_is_summarised_by_its_term_count_and_cut_off():
    r = run("expand", expression="(x+y+z+1)^40")
    assert r.summary == "sum of 12,341 terms" and r.truncated and len(r.text) == operations.MAX_RESULT_CHARS


def test_a_result_beyond_the_digit_limit_is_summarised_not_printed(monkeypatch):
    """Simulate Python refusing to print the number (the guard that used to crash): the result must still be sane."""
    original = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(640)
    try:
        r = run("evaluate", expression="999^999")
    finally:
        sys.set_int_max_str_digits(original)
    assert r.truncated and r.text.startswith("<integer with 2,997 digits") and "cut off" in r.note


def test_matrices_with_enormous_entries_are_recognised():
    big = "999^999"
    r = run("matrix", operation="transpose", a=f"[[{big}, {big}], [{big}, {big}]]", b=None)
    assert r.summary.startswith("2×2 matrix") and r.latex is None and not r.truncated


def test_ordinary_results_are_untouched():
    r = run("expand", expression="(x+1)^20")
    assert r.summary is None and r.latex and not r.truncated
    assert run("matrix", operation="inverse", a="[[1,2],[3,4]]", b=None).summary is None


async def test_the_worker_process_handles_overflow_too():
    r = await MathEngine().run("evaluate", expression="10^999*10^999*10^999*10^999*10^999")
    assert "4,996 digits" in r.summary and len(r.text) == 4996


# ------------------------------------------------------------------------------------------ formatting

def test_the_overflow_threshold():
    assert not is_overflow(MathResult(text="1" * INLINE_RESULT_CHARS))
    assert is_overflow(MathResult(text="1" * (INLINE_RESULT_CHARS + 1)))
    assert is_overflow(MathResult(text="<cut>", truncated=True))
    assert not is_overflow(MathResult(text="1" * 5000, established=False))


def test_an_oversized_result_is_summarised_in_a_short_message():
    r = run("evaluate", expression="999^999")
    msg = format_result("Evaluate", "999^999", r, has_attachment=True)
    assert "too large to display" in msg and "2,997 digits" in msg and RESULT_FILENAME in msg
    assert str(999**999)[:50] not in msg and len(msg) < 400


def test_without_an_attachment_the_message_does_not_claim_one():
    r = MathResult(text="9" * 5000, summary="integer with 5,000 digits", truncated=True)
    msg = format_result("Evaluate", "x", r)
    assert RESULT_FILENAME not in msg and "too long to attach" in msg


def test_a_result_with_no_summary_reports_its_length():
    msg = format_result("Solve", "x", MathResult(text="a" * 900), has_attachment=True)
    assert "900 characters" in msg


def test_attachment_text_is_complete_only_for_complete_oversized_results():
    big = MathResult(text="7" * 1000)
    assert attachment_text(big) == "7" * 1000 + "\n"
    assert attachment_text(MathResult(text="7" * 100)) is None                  # fits inline: nothing to attach
    assert attachment_text(MathResult(text="7" * 1000, truncated=True)) is None  # incomplete: never present it as the whole


def test_inline_results_with_a_summary_show_it_without_attachments():
    r = run("evaluate", expression="2^1000-1")
    msg = format_result("Evaluate", "2^1000-1", r)
    assert "```" in msg and "Summary: integer with 302 digits" in msg and RESULT_FILENAME not in msg


@pytest.mark.parametrize("expression", ["999^999", "10^999*10^999*10^999*10^999*10^999", "7^1000", "2^1000-1"])
def test_no_message_ever_approaches_discords_limit(expression):
    r = run("evaluate", expression=expression)
    assert len(format_result("Evaluate", expression, r, has_attachment=attachment_text(r) is not None)) < MAX_MESSAGE


# ------------------------------------------------------------------------------------------ the command

async def ask(command, *args):
    calc = Calc(InProcessEngine(), renderer=None)
    i = FakeInteraction()
    await getattr(calc, command).callback(calc, i, *args)
    return i.sent[0]


async def test_evaluate_attaches_the_full_number_and_keeps_the_chat_short():
    content, kwargs = await ask("evaluate", "999^999", 15)
    assert "too large to display" in content and len(content) < 400
    attachment = kwargs["file"]
    assert attachment.filename == "result.txt" and attachment.fp.read().decode() == str(999**999) + "\n"


async def test_simplify_and_matrix_handle_overflow_the_same_way():
    content, kwargs = await ask("simplify", "7^1000")
    assert "846 digits" in content and kwargs["file"].filename == "result.txt"
    content, kwargs = await ask("matrix", "transpose", "[[999^999, 1], [1, 1]]", None)
    assert "too large to display" in content


async def test_the_crash_case_now_gets_a_normal_answer():
    content, kwargs = await ask("evaluate", "10^999*10^999*10^999*10^999*10^999", 15)
    assert "4,996 digits" in content and "failed" not in content and kwargs["file"].filename == "result.txt"


async def test_a_cut_off_result_is_not_attached():
    content, kwargs = await ask("expand", "(x+y+z+1)^40")
    assert "12,341 terms" in content and "too long to attach" in content and "file" not in kwargs


async def test_ordinary_answers_are_unchanged():
    content, kwargs = await ask("evaluate", "2^10", 15)
    assert "1024" in content and "file" not in kwargs and "too large" not in content
