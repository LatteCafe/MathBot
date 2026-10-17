from cogs.calc import Calc
from cogs.formatting import MAX_MESSAGE, format_error, format_result
from math_engine.engine import MathEngine
from math_engine.results import MathResult


def test_exact_and_approximate_are_labelled_separately():
    msg = format_result("Simplify", "sqrt(8)", MathResult(text="2*sqrt(2)", approximation="2.828427124746190"))
    assert "Exact result" in msg and "Approximate (decimal)" in msg


def test_unestablished_result_is_clearly_flagged():
    msg = format_result("Solve", "cos(x)=x", MathResult(text="Could not find the solutions exactly.", established=False))
    assert "Not established" in msg and "Exact result" not in msg


def test_user_text_cannot_break_out_of_code_formatting():
    msg = format_result("Simplify", "x``` @everyone", MathResult(text="x```y"))
    assert "x```" not in msg and "y```" not in msg.replace("\n```", "")


def test_long_output_is_truncated_below_discord_limit():
    msg = format_result("Simplify", "x", MathResult(text="a" * 5000, note="n" * 5000))
    assert len(msg) <= MAX_MESSAGE


def test_error_formatting():
    assert format_error("input", "bad").startswith("❌")
    assert format_error("timeout", "slow").startswith("⏱️")


def test_calc_cog_registers_expected_commands():
    names = {c.name for c in Calc(MathEngine()).get_app_commands()}
    assert names == {"simplify", "diff", "solve"}
