"""Drive the real slash-command handlers with a stand-in Interaction (real engine, real renderer).

This does not replace testing against live Discord, but it checks the wiring: defer, then exactly one
follow-up with the right text and attachment, and graceful fallbacks.
"""
import discord
import pytest

from cogs.calc import Calc
from cogs.latex import Latex
from math_engine.engine import MathEngine
from math_engine.sandbox import Sandbox
from rendering.renderer import LatexRenderer


class FakeInteraction:
    def __init__(self):
        self.deferred = False
        self.sent = []          # (content, kwargs) for each followup.send
        outer = self

        class Response:
            async def defer(self, **kw):
                outer.deferred = True

            def is_done(self):
                return outer.deferred

        class Followup:
            async def send(self, content=None, **kw):
                outer.sent.append((content, kw))

        self.response, self.followup = Response(), Followup()


@pytest.fixture(scope="module")
def sandbox():
    return Sandbox()


async def test_simplify_sends_text_and_an_image(sandbox):
    calc = Calc(MathEngine(sandbox=sandbox), LatexRenderer(sandbox))
    i = FakeInteraction()
    await calc.simplify.callback(calc, i, "(x^2-1)/(x-1)")
    assert i.deferred and len(i.sent) == 1
    content, kw = i.sent[0]
    assert "x + 1" in content
    assert isinstance(kw["file"], discord.File) and kw["file"].filename == "result.png"


async def test_solve_with_approximation_sends_both(sandbox):
    calc = Calc(MathEngine(sandbox=sandbox), LatexRenderer(sandbox))
    i = FakeInteraction()
    await calc.solve.callback(calc, i, "x^2-2=0", None, "real")
    content, kw = i.sent[0]
    assert "Approximate (decimal)" in content and "1.41421356" in content and "file" in kw


async def test_unestablished_result_has_no_image(sandbox):
    calc = Calc(MathEngine(sandbox=sandbox), LatexRenderer(sandbox))
    i = FakeInteraction()
    await calc.solve.callback(calc, i, "cos(x)=x", None, "real")
    content, kw = i.sent[0]
    assert "Not established" in content and "file" not in kw


async def test_falls_back_to_plain_text_when_the_renderer_is_unavailable(sandbox):
    calc = Calc(MathEngine(sandbox=sandbox), renderer=None)
    i = FakeInteraction()
    await calc.diff.callback(calc, i, "x^3", None, 2)
    content, kw = i.sent[0]
    assert "6*x" in content and "```" in content and "file" not in kw


async def test_falls_back_to_text_when_the_result_cannot_be_typeset(sandbox):
    """d/dx |x|^3 comes back as a piecewise (\\begin{cases}), which the renderer rejects."""
    calc = Calc(MathEngine(sandbox=sandbox), LatexRenderer(sandbox))
    i = FakeInteraction()
    await calc.diff.callback(calc, i, "abs(x)^3", None, 1)
    content, kw = i.sent[0]
    assert "Exact result" in content and "file" not in kw


async def test_bad_calculator_input_shows_a_friendly_error(sandbox):
    calc = Calc(MathEngine(sandbox=sandbox), LatexRenderer(sandbox))
    i = FakeInteraction()
    await calc.simplify.callback(calc, i, "foo(x)")
    content, kw = i.sent[0]
    assert content.startswith("❌") and "Unknown function" in content and "file" not in kw


async def test_latex_command_sends_the_image_and_the_source(sandbox):
    cog = Latex(LatexRenderer(sandbox))
    i = FakeInteraction()
    await cog.latex.callback(cog, i, r"\int_0^1 x^2\,dx")
    content, kw = i.sent[0]
    assert r"\int_0^1" in content
    assert kw["file"].filename == "latex.png"


async def test_latex_command_reports_malformed_input_without_a_traceback(sandbox):
    cog = Latex(LatexRenderer(sandbox))
    i = FakeInteraction()
    await cog.latex.callback(cog, i, r"\frac{1}{")
    content, kw = i.sent[0]
    assert content.startswith("❌") and "Could not render" in content and "file" not in kw
    assert "Traceback" not in content


async def test_latex_command_handles_a_matrix(sandbox):
    cog = Latex(LatexRenderer(sandbox))
    i = FakeInteraction()
    await cog.latex.callback(cog, i, r"\begin{pmatrix}1&2\\3&4\end{pmatrix}")
    assert i.sent[0][1]["file"].filename == "latex.png"


async def test_integrate_definite_sends_text_image_and_bounds(sandbox):
    calc = Calc(MathEngine(sandbox=sandbox), LatexRenderer(sandbox))
    i = FakeInteraction()
    await calc.integrate.callback(calc, i, "exp(-x^2)", None, "-oo", "oo")
    content, kw = i.sent[0]
    assert "from -oo to oo" in content and "sqrt(pi)" in content and "1.77245385" in content
    assert kw["file"].filename == "result.png"


async def test_integrate_with_only_one_bound_is_a_friendly_error(sandbox):
    calc = Calc(MathEngine(sandbox=sandbox), LatexRenderer(sandbox))
    i = FakeInteraction()
    await calc.integrate.callback(calc, i, "x", None, "0", None)
    content, kw = i.sent[0]
    assert content.startswith("❌") and "both a lower and an upper" in content and "file" not in kw


async def test_limit_that_does_not_exist_says_so_and_has_no_image(sandbox):
    calc = Calc(MathEngine(sandbox=sandbox), LatexRenderer(sandbox))
    i = FakeInteraction()
    await calc.limit.callback(calc, i, "1/x", "0", None, "both")
    content, kw = i.sent[0]
    assert "Does not exist" in content and "file" not in kw


async def test_limit_via_the_command_with_a_direction(sandbox):
    calc = Calc(MathEngine(sandbox=sandbox), LatexRenderer(sandbox))
    i = FakeInteraction()
    await calc.limit.callback(calc, i, "1/x", "0", None, "+")
    assert "oo" in i.sent[0][0] and "from the right" in i.sent[0][0]


async def test_evaluate_is_shown_as_an_approximation_without_an_image(sandbox):
    calc = Calc(MathEngine(sandbox=sandbox), LatexRenderer(sandbox))
    i = FakeInteraction()
    await calc.evaluate.callback(calc, i, "pi", 20)
    content, kw = i.sent[0]
    assert "Approximate value" in content and "3.1415926535897932385" in content and "file" not in kw


async def test_factor_and_expand_commands(sandbox):
    calc = Calc(MathEngine(sandbox=sandbox), LatexRenderer(sandbox))
    i1, i2 = FakeInteraction(), FakeInteraction()
    await calc.factor.callback(calc, i1, "x^2-1")
    await calc.expand.callback(calc, i2, "(x+1)^3")
    assert "(x - 1)*(x + 1)" in i1.sent[0][0] and "file" in i1.sent[0][1]
    assert "x^3 + 3*x^2 + 3*x + 1" in i2.sent[0][0]
