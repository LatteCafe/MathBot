import pytest

from math_engine import operations
from math_engine.errors import InputError


def run(op, **args):
    return operations.run(op, args)


def test_simplify_exact():
    r = run("simplify", expression="(x^2 - 1)/(x - 1)")
    assert r.text == "x + 1"
    assert r.approximation is None and r.established


def test_simplify_integer_has_no_approximation():
    r = run("simplify", expression="sqrt(2)*sqrt(2)")
    assert r.text == "2" and r.approximation is None


def test_simplify_irrational_has_separate_approximation():
    r = run("simplify", expression="sqrt(8)")
    assert r.text == "2*sqrt(2)"
    assert r.approximation.startswith("2.828427124746")


def test_decimals_are_kept_exact():
    assert run("simplify", expression="0.5 + 0.25").text == "3/4"


def test_division_by_zero_is_reported():
    with pytest.raises(InputError, match="undefined"):
        run("simplify", expression="1/0")


def test_diff_basic_and_order():
    assert run("diff", expression="x^3").text == "3*x^2"
    assert run("diff", expression="x^3", order=2).text == "6*x"


def test_diff_product_rule():
    text = run("diff", expression="x*sin(x)").text
    assert "sin(x)" in text and "cos(x)" in text


def test_diff_assumes_real_variables():
    assert run("diff", expression="abs(x)").text == "sign(x)"
    assert run("diff", expression="sqrt(x^2)").text == "sign(x)"


def test_diff_requires_variable_when_ambiguous():
    with pytest.raises(InputError, match="several variables"):
        run("diff", expression="x*y")
    assert run("diff", expression="x*y", variable="y").text == "x"


def test_diff_rejects_variable_not_in_expression():
    with pytest.raises(InputError, match="does not appear"):
        run("diff", expression="t^2", variable="x")


@pytest.mark.parametrize("order", [0, 6, -1])
def test_diff_rejects_bad_order(order):
    with pytest.raises(InputError):
        run("diff", expression="x^2", order=order)


def test_solve_quadratic_real():
    r = run("solve", equation="x^2 - 4 = 0")
    assert r.text == "x = -2, x = 2"
    assert r.approximation is None


def test_solve_irrational_roots_show_approximation():
    r = run("solve", equation="x^2 - 2 = 0")
    assert "sqrt(2)" in r.text
    assert "1.41421356" in r.approximation


def test_solve_no_real_solutions_but_complex_ones():
    real = run("solve", equation="x^2 + 1 = 0")
    assert "No solutions" in real.text and real.established
    cplx = run("solve", equation="x^2 + 1 = 0", domain="complex")
    assert cplx.text == "x = -I, x = I"


def test_solve_without_equals_means_equals_zero():
    assert run("solve", equation="x - 3").text == "x = 3"


def test_solve_unsolvable_is_not_claimed_to_have_no_solutions():
    r = run("solve", equation="cos(x) = x")
    assert r.established is False
    assert "NOT mean there are no solutions" in r.note


def test_solve_requires_variable_when_ambiguous():
    with pytest.raises(InputError, match="several variables"):
        run("solve", equation="x + y = 3")
    assert run("solve", equation="x + y = 3", variable="y").text == "y = 3 - x"


def test_solve_rejects_bad_domain():
    with pytest.raises(InputError):
        run("solve", equation="x = 1", domain="quaternion")


def test_unknown_operation():
    with pytest.raises(InputError):
        operations.run("exec", {})
