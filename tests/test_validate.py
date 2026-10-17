import pytest

from math_engine.errors import InputError
from math_engine.validate import check_inputs, normalize, split_equation, validate_expression, validate_variable


@pytest.mark.parametrize("text", [
    "x^2 + 3x", "2sin(x)cos(x)", "(x+1)(x-1)", "sqrt(2)/2", "e^(x^2)", "x**2", "0.5*x",
    "log(x, 2)", "pi*r^2", "2^(1/2)", "(2^3)^2", "x(x+1)", "-x + +y", "1.5e".replace("e", "*e"),
])
def test_accepts_valid_expressions(text):
    validate_expression(text)


@pytest.mark.parametrize("text", [
    "__import__('os').system('ls')", "x.__class__", "open('f')", "lambda: 1", "x[0]", "foo(x)",
    "[1, 2]", "'a'", "x; y", "x if y else z", "x == y", "1 +", "(((", "", "   ", "xy", "1e999",
    "x" * 300, "9**9**9", "x**100000", "2**(1000*1000*1000)", "(10**999)**1000", "2**(10**999)",
    "x // 2", "x % 2", "x & y", "10000000000000", "α + 1",
])
def test_rejects_unsafe_or_invalid_expressions(text):
    with pytest.raises(InputError):
        validate_expression(text)


def test_normalize_implicit_multiplication_and_powers():
    assert normalize("2x") == "2*x"
    assert normalize("x^2") == "x**2"
    assert normalize("(x+1)(x-1)") == "(x+1)*(x-1)"
    assert normalize("2sin(x)cos(x)") == "2*sin(x)*cos(x)"
    assert normalize("x(x+1)") == "x*(x+1)"


def test_length_limit_is_configurable():
    text = "x+" * 24 + "x"   # 49 characters
    validate_expression(text, max_length=49)
    with pytest.raises(InputError, match="too long"):
        validate_expression(text, max_length=48)


def test_split_equation():
    assert split_equation("x^2 = 4") == ("x^2 ", " 4")
    assert split_equation("x^2 == 4") == ("x^2 ", " 4")
    assert split_equation("x^2 - 4") == ("x^2 - 4", "0")


@pytest.mark.parametrize("text", ["x = 1 = 2", "= 4", "x ="])
def test_split_equation_rejects_malformed(text):
    with pytest.raises(InputError):
        split_equation(text)


@pytest.mark.parametrize("name", ["x", "y", "T"])
def test_valid_variables(name):
    assert validate_variable(name) == name


@pytest.mark.parametrize("name", ["xy", "e", "1", "", "__"])
def test_invalid_variables(name):
    with pytest.raises(InputError):
        validate_variable(name)


def test_check_inputs_rejects_unknown_operation_and_bad_variable():
    with pytest.raises(InputError, match="Unknown operation"):
        check_inputs("rm_rf", {})
    with pytest.raises(InputError):
        check_inputs("diff", {"expression": "x^2", "variable": "xy"})
    check_inputs("solve", {"equation": "x^2 = 4"})
