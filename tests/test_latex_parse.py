import pytest

from math_engine.errors import InputError
from rendering.parse import MatrixSegment, MathSegment, parse_latex


def test_plain_math_is_one_segment():
    assert parse_latex(r"\frac{a}{b}") == [MathSegment(r"\frac{a}{b}")]


@pytest.mark.parametrize("text", ["$x^2$", "$$x^2$$", r"\[x^2\]", r"\(x^2\)", "  $ x^2 $  "])
def test_surrounding_math_delimiters_are_stripped(text):
    assert parse_latex(text) == [MathSegment("x^2")]


def test_newlines_become_spaces():
    assert parse_latex("a +\n b") == [MathSegment("a + b")]


def test_pmatrix_rows_and_cells():
    (seg,) = parse_latex(r"\begin{pmatrix} 1 & 2 \\ 3 & 4 \end{pmatrix}")
    assert seg == MatrixSegment("paren", (("1", "2"), ("3", "4")))


@pytest.mark.parametrize("env,style", [("matrix", "none"), ("pmatrix", "paren"), ("bmatrix", "bracket"), ("vmatrix", "bar")])
def test_matrix_styles(env, style):
    (seg,) = parse_latex(rf"\begin{{{env}}} a & b \end{{{env}}}")
    assert seg.style == style


def test_trailing_row_separator_does_not_add_a_row():
    (seg,) = parse_latex(r"\begin{pmatrix} 1 & 2 \\ 3 & 4 \\ \end{pmatrix}")
    assert len(seg.rows) == 2


def test_ragged_rows_are_padded():
    (seg,) = parse_latex(r"\begin{bmatrix} 1 & 2 & 3 \\ 4 \end{bmatrix}")
    assert seg.rows == (("1", "2", "3"), ("4", "", ""))


def test_math_around_matrices_is_kept_in_order():
    segs = parse_latex(r"A = \begin{pmatrix}1\end{pmatrix} + B")
    assert [type(s).__name__ for s in segs] == ["MathSegment", "MatrixSegment", "MathSegment"]
    assert segs[0].text == "A =" and segs[2].text == "+ B"


def test_two_matrices():
    segs = parse_latex(r"\begin{pmatrix}1\end{pmatrix}\begin{pmatrix}2\end{pmatrix}")
    assert len(segs) == 2 and all(isinstance(s, MatrixSegment) for s in segs)


@pytest.mark.parametrize("text,fragment", [
    ("", "empty"), ("   ", "empty"),
    ("x" * 301, "too long"),
    ("a $ b", "$"),
    (r"\begin{cases} 1 \end{cases}", "not supported"),
    (r"\begin{pmatrix} 1", "Missing"),
    (r"\end{pmatrix}", "without a matching"),
    (r"\begin{pmatrix} \begin{pmatrix}1\end{pmatrix} \end{pmatrix}", "Nested"),
    (r"\begin{pmatrix}\end{pmatrix}", "empty"),
    ("x\x00y", "unprintable"),
])
def test_rejected_inputs(text, fragment):
    with pytest.raises(InputError, match=fragment):
        parse_latex(text)


def test_matrix_size_limit():
    row = " & ".join(["1"] * 11)
    with pytest.raises(InputError, match="larger than"):
        parse_latex(rf"\begin{{pmatrix}} {row} \end{{pmatrix}}")
    rows = r" \\ ".join(["1"] * 11)
    with pytest.raises(InputError, match="larger than"):
        parse_latex(rf"\begin{{pmatrix}} {rows} \end{{pmatrix}}")


def test_length_limit_is_configurable():
    parse_latex("x" * 50, max_length=50)
    with pytest.raises(InputError, match="too long"):
        parse_latex("x" * 51, max_length=50)
