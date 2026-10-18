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


# ============================================================ Phase 2b: factor, expand, integrate, limit, evaluate

def test_factor_polynomials():
    assert run("factor", expression="x^2-1").text == "(x - 1)*(x + 1)"
    assert run("factor", expression="x^3 - 6x^2 + 11x - 6").text == "(x - 3)*(x - 2)*(x - 1)"
    assert run("factor", expression="x^2*y + x*y^2").text == "x*y*(x + y)"


def test_factor_says_so_when_nothing_factors_over_the_rationals():
    r = run("factor", expression="x^2-2")
    assert r.text == "x^2 - 2" and "No factorization found" in r.note


def test_expand():
    assert run("expand", expression="(x+1)^3").text == "x^3 + 3*x^2 + 3*x + 1"
    assert run("expand", expression="(x+1)(x-1)").text == "x^2 - 1"
    assert run("expand", expression="x^2+1").note == "Already expanded."


def test_integrate_indefinite():
    r = run("integrate", expression="x^2")
    assert r.text == "x^3/3" and "+ C" in r.note
    assert run("integrate", expression="5").text == "5*x"            # constant integrand defaults to x
    assert "ln|argument|" in run("integrate", expression="1/x").note  # log caveat


def test_integrate_unresolvable_is_not_claimed_to_have_no_antiderivative():
    r = run("integrate", expression="x^x")
    assert r.established is False and "does NOT mean" in r.note


def test_integrate_definite_exact_with_separate_approximation():
    assert run("integrate", expression="x^2", lower="0", upper="1").text == "1/3"
    r = run("integrate", expression="exp(-x^2)", lower="-oo", upper="oo")
    assert r.text == "sqrt(pi)" and r.approximation.startswith("1.77245385")


def test_integrate_pole_inside_interval_is_not_established():
    r = run("integrate", expression="1/x", lower="-1", upper="1")
    assert r.established is False and "singularity" in r.note


def test_integrate_divergent_integral_is_reported_as_diverging():
    r = run("integrate", expression="1/x", lower="0", upper="1")
    assert r.text == "oo" and "diverges" in r.note and r.established


def test_integrate_warns_when_a_real_integrand_gives_a_complex_result():
    r = run("integrate", expression="1/(x-1)^(1/3)", lower="0", upper="2")
    assert "Warning: the result is complex" in r.note and "branch cut" in r.note


def test_integrate_argument_errors():
    with pytest.raises(InputError, match="both a lower and an upper"):
        run("integrate", expression="x", lower="0")
    with pytest.raises(InputError, match="several variables"):
        run("integrate", expression="x*y")
    assert run("integrate", expression="x*y", variable="y").text == "x*y^2/2"
    with pytest.raises(InputError, match="cannot contain the integration variable"):
        run("integrate", expression="x^2", lower="x", upper="1")


def test_limit_finite_and_at_infinity():
    assert run("limit", expression="sin(x)/x", point="0").text == "1"
    assert run("limit", expression="(x^2-1)/(x-1)", point="1").text == "2"
    assert run("limit", expression="exp(-x)", point="oo").text == "0"
    r = run("limit", expression="(1+1/x)^x", point="oo")
    assert r.text == "E" and r.approximation.startswith("2.71828")


def test_limit_one_sided_differs_from_two_sided():
    assert run("limit", expression="1/x", point="0", direction="+").text == "oo"
    assert run("limit", expression="1/x", point="0", direction="-").text == "-oo"
    r = run("limit", expression="1/x", point="0")
    assert "Does not exist" in r.text and "-oo" in r.text and "oo" in r.text
    assert "Does not exist" in run("limit", expression="abs(x)/x", point="0").text


def test_limit_two_sided_infinite_limit_is_not_reported_as_nonexistent():
    """Regression: both sides are +oo. Subtracting gives oo - oo = nan, which was once misread as 'different'."""
    r = run("limit", expression="1/x^2", point="0")
    assert r.text == "oo" and "infinite" in r.note
    assert run("limit", expression="-1/x^2", point="0").text == "-oo"


def test_limit_oscillation_is_reported_not_guessed():
    r = run("limit", expression="sin(x)", point="oo")
    assert "Does not exist" in r.text and "oscillating" in r.text


def test_limit_argument_errors():
    with pytest.raises(InputError, match="cannot contain the variable"):
        run("limit", expression="x", point="x")
    with pytest.raises(InputError, match="direction"):
        run("limit", expression="x", point="0", direction="up")


def test_evaluate_is_labelled_approximate_with_requested_digits():
    r = run("evaluate", expression="pi")
    assert r.approximate_only and r.text == "3.14159265358979" and r.latex is None
    assert run("evaluate", expression="pi", digits=40).text.startswith("3.14159265358979323846264338327950288419")
    assert run("evaluate", expression="1/3", digits=5).text == "0.33333"


def test_evaluate_integers_are_exact_not_approximate():
    r = run("evaluate", expression="2^10")
    assert r.text == "1024" and not r.approximate_only


def test_evaluate_rejects_variables_and_bad_digits():
    with pytest.raises(InputError, match="contains variables"):
        run("evaluate", expression="x+1")
    for digits in (0, 51, -3):
        with pytest.raises(InputError, match="digits"):
            run("evaluate", expression="pi", digits=digits)


def test_very_long_results_are_truncated_and_not_typeset():
    r = run("expand", expression="(x+y+z+1)^40")
    assert len(r.text) <= operations.MAX_RESULT_CHARS + 1
    assert r.latex is None and "too long" in r.note
