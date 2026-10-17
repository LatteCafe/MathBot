"""Rendering tests. Most call the drawing code in-process; a few go through the real worker subprocess."""
import io
import struct

import pytest
from PIL import Image

from math_engine.errors import InputError
from math_engine.sandbox import Sandbox
from rendering.draw import render_png
from rendering.parse import parse_latex
from rendering.renderer import LatexRenderer


def render(tex, **kw):
    return render_png(parse_latex(tex, kw.pop("max_length", 1500)), **kw)


def size(png):
    assert png[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", png[16:24])  # (width, height) from the IHDR chunk


# The notation named in the project spec, plus a few extras.
SUPPORTED = [
    r"\frac{a+b}{c}", r"\dfrac{1}{2}", r"\sqrt{x^2+1}", r"\sqrt[3]{x}", r"\binom{n}{k}",
    r"\int_0^1 x^2\,dx", r"\int_{-\infty}^{\infty} e^{-x^2}\,dx = \sqrt{\pi}",
    r"\sum_{n=1}^{\infty} \frac{1}{n^2} = \frac{\pi^2}{6}", r"\prod_{k=1}^{n} k",
    r"\lim_{x \to 0} \frac{\sin x}{x} = 1",
    r"\alpha+\beta+\gamma+\delta+\Omega+\pi+\theta", r"\mathbb{R}, \mathcal{L}, \infty, \partial, \nabla",
    r"\left( \frac{a}{b} \right)", r"\left|x\right|", r"\leq \neq \approx \pm \cdot \times",
    r"\sin^2 x + \cos^2 x = 1", r"\hat{x}+\vec{v}+\overline{z}", r"x_{i_j}^{k}", r"\text{if } x > 0",
]


@pytest.mark.parametrize("tex", SUPPORTED)
def test_common_notation_renders(tex):
    w, h = size(render(tex))
    assert w > 20 and h > 20


@pytest.mark.parametrize("env", ["matrix", "pmatrix", "bmatrix", "vmatrix"])
def test_matrix_environments_render(env):
    w, h = size(render(rf"\begin{{{env}}} 1 & 2 \\ 3 & 4 \end{{{env}}}"))
    assert w > 50 and h > 50


def test_matrix_with_surrounding_math_and_complex_cells():
    render(r"A = \begin{pmatrix} \frac{1}{2} & \sqrt{2} \\ x^2 & 0 \end{pmatrix}^{-1}")
    render(r"\begin{bmatrix} a & b \\ c & d \end{bmatrix}\begin{bmatrix} x \\ y \end{bmatrix} = \begin{bmatrix} ax+by \\ cx+dy \end{bmatrix}")


def test_matrix_size_scales_with_contents():
    w1, h1 = size(render(r"\begin{pmatrix} 1 \end{pmatrix}"))
    w3, h3 = size(render(r"\begin{pmatrix} 1&2&3 \\ 4&5&6 \\ 7&8&9 \end{pmatrix}"))
    assert w3 > 2 * w1 and h3 > 2 * h1


def test_output_is_opaque_white_so_it_reads_on_dark_and_light_themes():
    img = Image.open(io.BytesIO(render(r"x^2"))).convert("RGBA")
    assert img.getpixel((0, 0)) == (255, 255, 255, 255)
    assert img.convert("L").getextrema()[0] < 80  # and there is dark ink somewhere


def test_fontsize_and_dpi_change_the_image_size():
    small = size(render("x^2", fontsize=10, dpi=100))
    large = size(render("x^2", fontsize=20, dpi=200))
    assert large[0] > 2 * small[0]


@pytest.mark.parametrize("tex", [r"\foo{x}", r"\frac{1}{", r"x^", r"\frac{a}{b", r"\begin{pmatrix} \foo \end{pmatrix}"])
def test_malformed_latex_gives_a_friendly_error(tex):
    with pytest.raises(InputError, match="Could not render that LaTeX") as info:
        render(tex)
    assert "Traceback" not in str(info.value) and len(str(info.value)) < 400


def test_unsupported_environment_is_reported_clearly():
    with pytest.raises(InputError, match="cases"):
        render(r"\begin{cases} 1 & x > 0 \\ 0 & \text{otherwise} \end{cases}")


def test_oversized_output_is_refused():
    with pytest.raises(InputError, match="too large"):
        render("x" * 280)


# --- Everything the calculator can output must either render or fail cleanly (the cog then falls back to text).
CALC_CASES = [
    ("simplify", {"expression": "(x^2-1)/(x-1)"}), ("simplify", {"expression": "sqrt(8)"}),
    ("simplify", {"expression": "abs(x)"}), ("simplify", {"expression": "atan(x)"}),
    ("simplify", {"expression": "sinh(x)*cosh(x)"}), ("simplify", {"expression": "e^(x^2)"}),
    ("simplify", {"expression": "pi*r^2/2"}), ("simplify", {"expression": "tan(x)^3"}),
    ("diff", {"expression": "x^3*sin(x)"}), ("diff", {"expression": "log(x)/x"}), ("diff", {"expression": "asin(x)"}),
    ("diff", {"expression": "abs(x)"}),
    ("solve", {"equation": "x^2-4=0"}), ("solve", {"equation": "x^2-2=0"}), ("solve", {"equation": "x^2+1=0"}),
    ("solve", {"equation": "x^2+1=0", "domain": "complex"}), ("solve", {"equation": "x+y=3", "variable": "y"}),
    ("solve", {"equation": "sin(x)=0"}), ("solve", {"equation": "x^2-x-1=0"}), ("solve", {"equation": "x^4+1=0", "domain": "complex"}),
]


@pytest.mark.parametrize("op,args", CALC_CASES)
def test_calculator_output_can_be_rendered(op, args):
    from math_engine import operations
    result = operations.run(op, args)
    assert result.latex
    render(result.latex, max_length=1500)


# --- Through the real worker subprocess ---

async def test_renderer_works_through_the_worker_process():
    png = await LatexRenderer(Sandbox()).render(r"\frac{a}{b}")
    assert size(png)[0] > 20


async def test_worker_reports_malformed_latex_as_input_error():
    with pytest.raises(InputError, match="Could not render"):
        await LatexRenderer(Sandbox()).render(r"\foo")


async def test_invalid_input_does_not_spawn_a_worker(monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("no worker should be spawned")

    monkeypatch.setattr("asyncio.create_subprocess_exec", boom)
    with pytest.raises(InputError):
        await LatexRenderer(Sandbox()).render(r"\begin{cases} 1 \end{cases}")


async def test_max_length_can_be_raised_per_call():
    renderer = LatexRenderer(Sandbox(), max_length=10)
    with pytest.raises(InputError, match="too long"):
        await renderer.render(r"\frac{abc}{def} + 1")
    png = await renderer.render(r"\frac{abc}{def} + 1", max_length=100)
    assert size(png)[0] > 20


async def test_warm_up_never_raises(monkeypatch):
    renderer = LatexRenderer(Sandbox())

    async def fail(*a, **k):
        raise RuntimeError("renderer broke")

    monkeypatch.setattr(renderer, "render", fail)
    await renderer.warm_up()  # must swallow the error so the bot still starts


async def test_warm_up_uses_a_long_timeout_so_the_font_cache_can_finish_building(monkeypatch):
    seen = {}

    async def fake_call(module, payload, *, timeout=None):
        seen["timeout"] = timeout
        import base64
        return {"png": base64.b64encode(b"x").decode()}

    sandbox = Sandbox()
    monkeypatch.setattr(sandbox, "call", fake_call)
    await LatexRenderer(sandbox).warm_up()
    assert seen["timeout"] >= 60


async def test_per_call_timeout_override_is_honoured():
    from math_engine.errors import ComputeTimeout
    with pytest.raises(ComputeTimeout, match="0.05"):
        await Sandbox(timeout=30).call("rendering.worker", {"latex": "x", "max_length": 300, "fontsize": 20, "dpi": 200},
                                       timeout=0.05)
