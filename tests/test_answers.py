import pytest

from math_engine.engine import MathEngine
from services.answers import Verdict, check_answer
from tests.potd_support import FailingEngine, InProcessEngine, make_bank, raw

NUM = make_bank(raw("num", answer="12")).get("num")
FRAC = make_bank(raw("frac", answer="3/8")).get("frac")
IRR = make_bank(raw("irr", answer="pi/4")).get("irr")
CHOICE = make_bank(raw("mc", answer_type="choice", answer="B", options=["one", "two", "three"])).get("mc")
V = Verdict


async def grade(problem, text, engine=None):
    return await check_answer(problem, text, engine or InProcessEngine())


@pytest.mark.parametrize("text", ["12", " 12 ", "+12", "12.0", "24/2", "12.000", "1 2".replace(" ", "")])
async def test_plain_numbers_are_compared_exactly_without_the_engine(text):
    assert (await grade(NUM, text, FailingEngine(RuntimeError("the engine must not be used")))).verdict is V.CORRECT


@pytest.mark.parametrize("text", ["13", "-12", "11.999", "1/12", "0", "120"])
async def test_wrong_plain_numbers_are_incorrect(text):
    assert (await grade(NUM, text, FailingEngine(RuntimeError("no engine")))).verdict is V.INCORRECT


@pytest.mark.parametrize("text", ["3/8", "0.375", "6/16", " 3 / 8 ", ".375", "75/200"])
async def test_equivalent_fractions_and_decimals_are_accepted(text):
    assert (await grade(FRAC, text)).verdict is V.CORRECT


@pytest.mark.parametrize("text", ["pi/4", "2*pi/8", "(pi)/(4)", "pi*1/4", "0.25*pi", "pi/2/2", "(pi/2)/2"])
async def test_equivalent_closed_forms_are_accepted(text):
    assert (await grade(IRR, text)).verdict is V.CORRECT


@pytest.mark.parametrize("text", ["pi/3", "pi", "1/4", "0.785398", "sqrt(2)", "x", "pi/4 + 1/1000000"])
async def test_wrong_closed_forms_and_decimal_approximations_are_incorrect(text):
    assert (await grade(IRR, text)).verdict is V.INCORRECT


async def test_a_decimal_too_long_to_represent_exactly_is_rejected_not_silently_rounded():
    r = await grade(IRR, "0.7853981633974483")              # 16 significant digits
    assert r.verdict is V.INVALID and "significant digits" in r.message


@pytest.mark.parametrize("text", ["", "   ", "foo(1)", "__import__('os')", "1e5", "[[1]]", "x" * 300, "1/0", "(((", "pi +"])
async def test_unreadable_answers_are_invalid_and_not_graded(text):
    r = await grade(IRR, text)
    assert r.verdict is V.INVALID and r.message


@pytest.mark.parametrize("text", ["B", "b", " B ", "(B)", "B.", "b)", "(b)."])
async def test_choice_answers_accept_common_ways_of_writing_a_letter(text):
    assert (await grade(CHOICE, text)).verdict is V.CORRECT


@pytest.mark.parametrize("text,verdict", [("A", V.INCORRECT), ("c", V.INCORRECT), ("D", V.INVALID), ("Z", V.INVALID),
                                          ("AB", V.INVALID), ("option B", V.INVALID), ("1", V.INVALID), ("", V.INVALID)])
async def test_choice_answers_outside_the_options_are_invalid_not_wrong(text, verdict):
    assert (await grade(CHOICE, text)).verdict is verdict


async def test_the_invalid_message_for_a_choice_lists_the_valid_letters():
    assert "A, B, C" in (await grade(CHOICE, "Z")).message


async def test_grading_through_the_real_sandboxed_engine():
    engine = MathEngine()
    assert (await check_answer(IRR, "2*pi/8", engine)).verdict is V.CORRECT
    assert (await check_answer(IRR, "pi/3", engine)).verdict is V.INCORRECT
    assert (await check_answer(IRR, "1/0", engine)).verdict is V.INVALID


async def test_the_verdict_never_contains_the_expected_answer():
    for text in ["wrong", "pi/3", "1/0", "foo(1)", "7"]:
        r = await grade(IRR, text)
        assert "pi/4" not in (r.message or "")
