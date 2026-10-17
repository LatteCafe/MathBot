import discord
import pytest

from cogs.calc import Calc
from cogs.formatting import MAX_MESSAGE, format_error, format_result
from cogs.latex import Latex
from math_engine.engine import MathEngine
from math_engine.errors import ComputeTimeout, InputError
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


def test_with_image_the_exact_result_is_a_copyable_line_not_a_code_block():
    msg = format_result("Simplify", "x+x", MathResult(text="2*x", latex="2 x"), has_image=True)
    assert "`2*x`" in msg and "```" not in msg


def test_with_image_long_results_point_to_the_image():
    msg = format_result("Simplify", "x", MathResult(text="a" * 400, latex="a"), has_image=True)
    assert "see image" in msg and "a" * 400 not in msg


def test_approximation_still_shown_separately_with_image():
    msg = format_result("Simplify", "sqrt(8)", MathResult(text="2*sqrt(2)", approximation="2.8284"), has_image=True)
    assert "Approximate (decimal)" in msg and "2.8284" in msg


def test_latex_cog_registers_its_command():
    assert {c.name for c in Latex(renderer=None).get_app_commands()} == {"latex"}


class FakeRenderer:
    def __init__(self, error=None):
        self.error, self.calls = error, []

    async def render(self, latex, *, max_length=None):
        self.calls.append((latex, max_length))
        if self.error:
            raise self.error
        return b"\x89PNG fake"


async def test_calc_attaches_an_image_when_rendering_works():
    renderer = FakeRenderer()
    picture = await Calc(MathEngine(), renderer)._render_image(MathResult(text="x + 1", latex="x + 1"))
    assert isinstance(picture, discord.File) and picture.filename == "result.png"
    assert renderer.calls == [("x + 1", 1500)]


@pytest.mark.parametrize("error", [InputError("unsupported"), ComputeTimeout("slow")])
async def test_calc_falls_back_to_text_when_rendering_fails(error):
    assert await Calc(MathEngine(), FakeRenderer(error))._render_image(MathResult(text="x", latex="x")) is None


async def test_calc_skips_rendering_when_there_is_nothing_to_draw():
    renderer = FakeRenderer()
    calc = Calc(MathEngine(), renderer)
    assert await calc._render_image(MathResult(text="could not solve", established=False)) is None
    assert await calc._render_image(MathResult(text="x", latex=None)) is None
    assert await Calc(MathEngine(), None)._render_image(MathResult(text="x", latex="x")) is None
    assert renderer.calls == []
