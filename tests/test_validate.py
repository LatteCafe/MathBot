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


def test_check_inputs_for_phase_2b_operations():
    check_inputs("factor", {"expression": "x^2-1"})
    check_inputs("integrate", {"expression": "x^2", "variable": "x", "lower": "0", "upper": "oo"})
    check_inputs("integrate", {"expression": "x^2", "lower": None, "upper": None})
    check_inputs("limit", {"expression": "sin(x)/x", "point": "0", "direction": "+"})
    check_inputs("evaluate", {"expression": "pi", "digits": 20})


@pytest.mark.parametrize("op,args", [
    ("integrate", {"expression": "x", "lower": "0"}),
    ("integrate", {"expression": "x", "upper": "1"}),
    ("integrate", {"expression": "x", "lower": "__import__('os')", "upper": "1"}),
    ("limit", {"expression": "x", "point": ""}),
    ("limit", {"expression": "x", "point": "foo(1)"}),
    ("evaluate", {"expression": ""}),
    ("expand", {"expression": "9**9**9"}),
])
def test_check_inputs_rejects_bad_phase_2b_input(op, args):
    with pytest.raises(InputError):
        check_inputs(op, args)


# ============================================================ matrices

from math_engine.validate import validate_matrix  # noqa: E402


@pytest.mark.parametrize("text,shape", [
    ("[[1,2],[3,4]]", (2, 2)), ("[[1]]", (1, 1)), ("[[a,b],[c,d]]", (2, 2)), ("[[1/2, sqrt(2)],[x^2, 0]]", (2, 2)),
    ("[[2x, 1]]", (1, 2)), (" [ [1, 2] , [3, 4] ] ", (2, 2)), ("[[1,2,3]]", (1, 3)), ("[[1],[2],[3]]", (3, 1)),
    ("[[1,2],[3,4],]", (2, 2)),
])
def test_valid_matrices(text, shape):
    rows = validate_matrix(text)
    assert (len(rows), len(rows[0])) == shape


@pytest.mark.parametrize("text", [
    "[1,2,3]", "[]", "[[]]", "[[1,2],[3]]", "[[1,2][3,4]]", "[[1,2],[3,4]][0]", "[[1,2],[3,4]]+[[1]]", "[[1,2]]*2",
    "[[[1]]]", "[[oo]]", "[['a']]", "[[1;2]]", "__import__('os')", "[[foo(1)]]", "[[x.real]]", "[[lambda: 1]]",
    "[[x**9**9**9]]", "[[1,2,3,4,5,6,7]]", "[[1]]" + " " * 900, "", "   ", "1+1", "x",
])
def test_invalid_matrices_are_rejected(text):
    with pytest.raises(InputError):
        validate_matrix(text)


def test_matrix_size_limit_applies_to_rows_and_columns():
    validate_matrix("[" + ",".join(["[" + ",".join(["1"] * 6) + "]"] * 6) + "]")
    with pytest.raises(InputError, match="larger than 6x6"):
        validate_matrix("[" + ",".join(["[1]"] * 7) + "]")


def test_ragged_matrix_error_says_which_row():
    with pytest.raises(InputError, match="row 1 has 3, row 2 has 2"):
        validate_matrix("[[1,2,3],[4,5]]")


def test_brackets_are_still_rejected_in_ordinary_expressions_with_a_hint():
    for text in ("[[1,2]]", "x[0]", "[1, 2]"):
        with pytest.raises(InputError, match="/matrix"):
            validate_expression(text)


def test_check_inputs_for_the_matrix_operation():
    check_inputs("matrix", {"operation": "determinant", "a": "[[1,2],[3,4]]", "b": None})
    check_inputs("matrix", {"operation": "add", "a": "[[1]]", "b": "[[2]]"})
    check_inputs("matrix", {"operation": "multiply", "a": "[[1,2]]", "b": "3"})


@pytest.mark.parametrize("args", [
    {"operation": "explode", "a": "[[1]]", "b": None},
    {"operation": "determinant", "a": "[[1]]", "b": "[[2]]"},      # unary operation given a B
    {"operation": "add", "a": "[[1]]", "b": None},                  # binary operation without B
    {"operation": "add", "a": "[[1]]", "b": "5"},                   # scalar only makes sense for multiply
    {"operation": "multiply", "a": "[[1]]", "b": "__import__('os')"},
    {"operation": "determinant", "a": "not a matrix", "b": None},
    {"operation": "add", "a": "[[1]]", "b": "[[1,2],[3]]"},
])
def test_check_inputs_rejects_bad_matrix_requests(args):
    with pytest.raises(InputError):
        check_inputs("matrix", args)
