"""Matrix operations: hand-checked cases, error handling, and independent correctness checks."""
import random
import re

import numpy as np
import pytest
import sympy

from math_engine import operations
from math_engine.convert import to_sympy_matrix
from math_engine.errors import InputError
from math_engine.validate import validate_matrix


def mat(operation, a, b=None):
    return operations.run("matrix", {"operation": operation, "a": a, "b": b})


def parse(text):
    """Parse a result's plain text back into a SymPy matrix (this is also what a user would paste back in)."""
    return to_sympy_matrix(validate_matrix(text))


def as_text(rows):
    return "[" + ",".join("[" + ",".join(str(x) for x in r) + "]" for r in rows) + "]"


# ---------------------------------------------------------------- hand-checked values

def test_determinant():
    assert mat("determinant", "[[1,2],[3,4]]").text == "-2"
    assert mat("determinant", "[[2,0,1],[1,3,2],[1,1,2]]").text == "6"        # 2(6-2) - 0*(2-2) + 1(1-3) = 8 - 2
    assert mat("determinant", "[[a,b],[c,d]]").text == "a*d - b*c"
    assert mat("determinant", "[[5]]").text == "5"


def test_inverse():
    r = mat("inverse", "[[1,2],[3,4]]")
    assert r.text == "[[-2, 1], [3/2, -1/2]]" and "determinant is -2" in r.note


def test_singular_matrix_is_reported_not_inverted():
    r = mat("inverse", "[[1,2],[2,4]]")
    assert "Not invertible" in r.text and r.latex is None


def test_symbolic_inverse_states_where_it_is_valid():
    r = mat("inverse", "[[a,b],[c,d]]")
    assert "a*d - b*c" in r.note and "not 0" in r.note


def test_transpose_trace_rank():
    assert mat("transpose", "[[1,2,3],[4,5,6]]").text == "[[1, 4], [2, 5], [3, 6]]"
    assert mat("trace", "[[1,2],[3,4]]").text == "5"
    assert mat("rank", "[[1,2],[2,4]]").text == "1"
    assert mat("rank", "[[1,2],[3,4]]").text == "2"
    assert mat("rank", "[[1,2,3],[2,4,6],[1,0,1]]").text == "2"


def test_rank_of_a_symbolic_matrix_carries_a_caveat():
    r = mat("rank", "[[a,b],[c,d]]")
    assert r.text == "2" and "generic values" in r.note


def test_rref_and_pivot_columns():
    r = mat("rref", "[[1,2,3],[2,4,6],[1,0,1]]")
    assert r.text == "[[1, 0, 1], [0, 1, 1], [0, 0, 0]]" and "Pivot columns: 1, 2" in r.note
    assert mat("rref", "[[1,2],[3,4]]").text == "[[1, 0], [0, 1]]"


def test_add_subtract_multiply():
    a, b = "[[1,2],[3,4]]", "[[5,6],[7,8]]"
    assert mat("add", a, b).text == "[[6, 8], [10, 12]]"
    assert mat("subtract", a, b).text == "[[-4, -4], [-4, -4]]"
    assert mat("multiply", a, b).text == "[[19, 22], [43, 50]]"
    assert mat("multiply", "[[1,2,3],[4,5,6]]", "[[1],[0],[2]]").text == "[[7], [16]]"


def test_matrix_multiplication_is_not_commutative():
    a, b = "[[1,2],[3,4]]", "[[0,1],[1,0]]"
    assert mat("multiply", a, b).text != mat("multiply", b, a).text


def test_scalar_multiplication():
    assert mat("multiply", "[[1,2],[3,4]]", "3").text == "[[3, 6], [9, 12]]"
    assert mat("multiply", "[[1,2],[3,4]]", "x/2").text == "[[x/2, x], [3*x/2, 2*x]]"


# ---------------------------------------------------------------- eigenvalues

def test_eigenvalues_exact_cases():
    assert mat("eigenvalues", "[[2,0],[0,3]]").text == "λ = 2, λ = 3"
    assert mat("eigenvalues", "[[1,1],[0,1]]").text == "λ = 1 (multiplicity 2)"
    assert mat("eigenvalues", "[[5]]").text == "λ = 5"
    assert mat("eigenvalues", "[[2,0,0],[0,3,4],[0,4,9]]").text == "λ = 1, λ = 2, λ = 11"


def test_eigenvalues_with_irrational_roots_show_decimals_separately():
    r = mat("eigenvalues", "[[1,2],[3,4]]")
    assert r.text == "λ = 5/2 - sqrt(33)/2, λ = 5/2 + sqrt(33)/2"
    assert "-0.37228132" in r.approximation and "5.37228132" in r.approximation


def test_complex_eigenvalues_have_no_pointless_decimal_version():
    r = mat("eigenvalues", "[[0,-1],[1,0]]")
    assert r.text == "λ = -I, λ = I" and r.approximation is None


def test_irreducible_cubic_is_shown_as_roots_of_a_named_polynomial():
    r = mat("eigenvalues", "[[0,1,0],[0,0,1],[1,3,0]]")        # characteristic polynomial: λ^3 - 3λ - 1
    assert "λ^3 - 3*λ - 1" in r.note and "decimal approximations" in r.note
    assert "1.87938524" in r.text and "-1.53208888" in r.text and "-0.34729635" in r.text
    assert "I" not in r.text                                       # real eigenvalues must not be shown via complex radicals


def test_symbolic_2x2_eigenvalues_are_exact_formulas():
    assert "sqrt(a^2 - 2*a*d + 4*b*c + d^2)" in mat("eigenvalues", "[[a,b],[c,d]]").text


def test_eigenvalues_not_found_in_closed_form_are_not_claimed_to_be_absent():
    r = mat("eigenvalues", "[[1,2,3],[a,5,6],[7,8,10]]")
    assert r.established is False and "does NOT mean" in r.note


def _eigenvalues_from(result):
    values = []
    pattern = r"λ\s*[=≈]\s*(.+?)(?:\s*\(multiplicity (\d+)\))?(?=,\s*λ|$)"
    for m in re.finditer(pattern, result.text):
        values += [complex(sympy.N(sympy.sympify(m.group(1).replace("^", "**"))))] * int(m.group(2) or 1)
    return values


def _random_matrix(rng, n, low=-3, high=3):
    return [[rng.randint(low, high) for _ in range(n)] for _ in range(n)]


STRUCTURED = [[[1, 1], [0, 1]], [[0, -1], [1, 0]], [[2, 1], [1, 2]], [[4, 1, 0], [1, 4, 1], [0, 1, 4]],
              [[0, 1, 0], [0, 0, 1], [1, 3, 0]], [[1, 2, 3], [4, 5, 6], [7, 8, 10]], [[2, 0, 0, 0], [0, 3, 0, 0], [0, 0, 3, 0], [0, 0, 0, 5]]]
RANDOM = [_random_matrix(random.Random(seed), 2 + seed % 5) for seed in range(1, 13)]   # sizes 2..6


@pytest.mark.parametrize("rows", STRUCTURED + RANDOM)
def test_eigenvalues_agree_with_numpy_and_with_trace_and_determinant(rows):
    """An independent check: NumPy's eigenvalue solver, plus sum = trace and product = determinant."""
    result = mat("eigenvalues", as_text(rows))
    assert result.established
    ours = _eigenvalues_from(result)
    reference = list(np.linalg.eigvals(np.array(rows, dtype=float)))
    assert len(ours) == len(reference) == len(rows)
    for value in ours:                         # each of our eigenvalues must match a distinct NumPy one
        distances = [abs(value - r) for r in reference]
        best = min(range(len(reference)), key=distances.__getitem__)
        assert distances[best] < 1e-5, (rows, ours, reference)
        reference.pop(best)
    M = sympy.Matrix(rows)
    assert abs(sum(ours) - complex(M.trace())) < 1e-8
    assert abs(np.prod(ours) - complex(M.det())) < 1e-6 * max(1, abs(complex(M.det())))


# ---------------------------------------------------------------- algebraic identities (independent of hand-picked values)

def _invertible(rows):
    return sympy.Matrix(rows).det() != 0


@pytest.mark.parametrize("rows", [m for m in RANDOM + STRUCTURED if _invertible(m)])
def test_matrix_times_its_inverse_is_the_identity(rows):
    inverse = mat("inverse", as_text(rows))
    assert parse(mat("multiply", as_text(rows), inverse.text).text) == sympy.eye(len(rows))


@pytest.mark.parametrize("seed", range(8))
def test_determinant_of_a_product_is_the_product_of_determinants(seed):
    rng = random.Random(100 + seed)
    n = 2 + seed % 4
    a, b = as_text(_random_matrix(rng, n)), as_text(_random_matrix(rng, n))
    product = mat("multiply", a, b)
    assert sympy.Integer(mat("determinant", product.text).text) == \
        sympy.Integer(mat("determinant", a).text) * sympy.Integer(mat("determinant", b).text)


@pytest.mark.parametrize("seed", range(6))
def test_transpose_of_a_product_is_the_reversed_product_of_transposes(seed):
    rng = random.Random(200 + seed)
    m, n, p = rng.randint(1, 4), rng.randint(1, 4), rng.randint(1, 4)
    a = as_text([[rng.randint(-3, 3) for _ in range(n)] for _ in range(m)])
    b = as_text([[rng.randint(-3, 3) for _ in range(p)] for _ in range(n)])
    left = mat("transpose", mat("multiply", a, b).text).text
    right = mat("multiply", mat("transpose", b).text, mat("transpose", a).text).text
    assert left == right


@pytest.mark.parametrize("rows", RANDOM)
def test_rank_matches_the_number_of_pivots_and_numpy(rows):
    assert int(mat("rank", as_text(rows)).text) == np.linalg.matrix_rank(np.array(rows, dtype=float))


def test_results_can_be_pasted_back_in():
    first = mat("inverse", "[[2,1],[7,4]]")
    assert mat("inverse", first.text).text == "[[2, 1], [7, 4]]"      # the inverse of the inverse is the original


# ---------------------------------------------------------------- errors

def test_shape_errors_are_specific():
    with pytest.raises(InputError, match="square matrix, but this one is 1×3"):
        mat("determinant", "[[1,2,3]]")
    with pytest.raises(InputError, match="1×2 matrix and a 2×1 matrix"):
        mat("add", "[[1,2]]", "[[1],[2]]")
    with pytest.raises(InputError, match=r"columns of A \(2\) must equal the number of rows of B \(1\)"):
        mat("multiply", "[[1,2]]", "[[1,2]]")


def test_argument_errors():
    with pytest.raises(InputError, match="only matrix A"):
        mat("determinant", "[[1]]", "[[2]]")
    with pytest.raises(InputError, match="needs a second matrix"):
        mat("add", "[[1]]")
    with pytest.raises(InputError, match="must be a matrix"):
        mat("add", "[[1]]", "5")
    with pytest.raises(InputError, match="Unknown matrix operation"):
        mat("explode", "[[1]]")


def test_symbolic_matrices_are_capped_but_numeric_ones_are_not():
    symbolic = "[" + ",".join("[" + ",".join(["a", "b", "c", "d", "e"]) + "]" for _ in range(5)) + "]"
    with pytest.raises(InputError, match="limited to 4x4"):
        mat("determinant", symbolic)
    numeric6 = as_text(_random_matrix(random.Random(5), 6))
    assert mat("determinant", numeric6).text.lstrip("-").isdigit()


def test_large_results_are_truncated_not_typeset():
    entries = "[" + ",".join("[" + ",".join(["(x+1)^20"] * 4) + "]" for _ in range(4)) + "]"
    r = mat("multiply", entries, entries)
    assert len(r.text) <= operations.MAX_RESULT_CHARS + 1
