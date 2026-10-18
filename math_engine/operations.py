"""SymPy operations. Runs in the worker process only (the bot process never imports this).

Principle: never present a result as established when it is not. SymPy signals trouble in several ways
(an unevaluated Integral/Limit, ``nan``, ``zoo``); each is turned into an explicit "not established" result.
"""
from __future__ import annotations

import sympy

from .convert import to_sympy, to_sympy_matrix
from .errors import InputError
from .results import MathResult
from .validate import (DEFAULT_MAX_LENGTH, MATRIX_BINARY, MATRIX_UNARY, validate_equation, validate_expression,
                       validate_matrix, validate_variable)

MAX_DERIVATIVE_ORDER = 5
MAX_DIGITS = 50
MAX_RESULT_CHARS = 4000   # longer results are truncated (and not typeset)
MAX_LATEX_CHARS = 3000
MAX_SYMBOLIC_MATRIX_DIM = 4  # a fully symbolic 5x5 determinant takes seconds and a 6x6 minutes, so cap those
NOT_AN_ANSWER = "That does NOT mean there is no answer, only that SymPy could not establish one."


def pretty(text: str) -> str:
    """SymPy prints powers as ``**``; show ``^`` which is what users type."""
    return text.replace("**", "^")


def _approximation(expr) -> str | None:
    """A decimal approximation, only for exact irrational/complex numbers (where it adds information)."""
    if expr.is_number and not expr.is_Rational and expr.is_finite:
        re, im = expr.as_real_imag()
        if re.is_Rational and im.is_Rational:
            return None  # an exact value such as 2 - 3*I: a decimal adds nothing
        return str(sympy.N(expr, 15))
    return None


def _join(*notes: str | None) -> str | None:
    return " ".join(n for n in notes if n) or None


def _make(result, note: str | None = None) -> MathResult:
    """Build a MathResult from a SymPy expression, guarding against enormous output."""
    text = pretty(str(result))
    if len(text) > MAX_RESULT_CHARS:
        return MathResult(text=text[:MAX_RESULT_CHARS] + "…", latex=None, approximation=None,
                          note=_join(note, "The result is too long to show in full."))
    latex = sympy.latex(result)
    return MathResult(text=text, latex=latex if len(latex) <= MAX_LATEX_CHARS else None,
                      approximation=_approximation(result), note=note)


def _not_established(text: str, note: str) -> MathResult:
    return MathResult(text=text, established=False, note=note)


def _parse(text: str, max_length: int):
    return to_sympy(validate_expression(text, max_length)[1])


def _pick_variable(free: set, requested: str | None, *, allow_absent: bool = False,
                   real: bool = False) -> sympy.Symbol:
    if requested:
        name = validate_variable(requested)
        symbol = sympy.Symbol(name, real=True) if real else sympy.Symbol(name)  # real=False would mean 'not real'
        if free and symbol not in free and not allow_absent:
            names = ", ".join(sorted(str(s) for s in free))
            raise InputError(f"The variable '{symbol}' does not appear in the expression (it contains: {names}).")
        return symbol
    if len(free) == 1:
        return next(iter(free))
    if not free:
        raise InputError("The expression has no variable to work with.")
    names = ", ".join(sorted(str(s) for s in free))
    raise InputError(f"The expression has several variables ({names}). Please specify which one to use.")


def _pick_variable_or_x(free: set, requested: str | None) -> sympy.Symbol:
    """Like _pick_variable, but a constant expression defaults to x (e.g. the integral of 5)."""
    if not requested and not free:
        return sympy.Symbol("x")
    return _pick_variable(free, requested, allow_absent=not free)


# ------------------------------------------------------------------------------------ operations

def simplify(expression: str, *, max_length: int = DEFAULT_MAX_LENGTH) -> MathResult:
    return _make(sympy.simplify(_parse(expression, max_length)))


def factor(expression: str, *, max_length: int = DEFAULT_MAX_LENGTH) -> MathResult:
    expr = _parse(expression, max_length)
    result = sympy.factor(expr)
    if result == expr:
        return _make(result, "No factorization found over the rational numbers "
                             "(it may still factor using irrational or complex numbers).")
    return _make(result, "Factored over the rational numbers.")


def expand(expression: str, *, max_length: int = DEFAULT_MAX_LENGTH) -> MathResult:
    expr = _parse(expression, max_length)
    result = sympy.expand(expr)
    return _make(result, "Already expanded." if result == expr else None)


def diff(expression: str, variable: str | None = None, order: int = 1, *,
         max_length: int = DEFAULT_MAX_LENGTH) -> MathResult:
    if not isinstance(order, int) or not 1 <= order <= MAX_DERIVATIVE_ORDER:
        raise InputError(f"The derivative order must be between 1 and {MAX_DERIVATIVE_ORDER}.")
    expr = _parse(expression, max_length)
    # Variables are assumed real: otherwise d/dx |x| comes back as an unreadable piecewise in re(x), im(x).
    expr = expr.xreplace({s: sympy.Symbol(s.name, real=True) for s in expr.free_symbols})
    var = _pick_variable(expr.free_symbols, variable, allow_absent=not expr.free_symbols, real=True)
    result = sympy.simplify(sympy.diff(expr, var, order))
    return _make(result, f"Derivative of order {order} with respect to {var} (variables assumed real).")


def integrate(expression: str, variable: str | None = None, lower: str | None = None,
              upper: str | None = None, *, max_length: int = DEFAULT_MAX_LENGTH) -> MathResult:
    if bool(lower) != bool(upper):
        raise InputError("Give both a lower and an upper bound, or neither (for an indefinite integral).")
    expr = _parse(expression, max_length)
    var = _pick_variable_or_x(expr.free_symbols, variable)

    if not lower:
        result = sympy.integrate(expr, var)
        if result.has(sympy.Integral) or result.has(sympy.nan):
            return _not_established("Could not find an antiderivative in closed form.", NOT_AN_ANSWER)
        log_caveat = "Where the argument of a log is negative, use ln|argument| instead." if result.has(sympy.log) else None
        return _make(result, _join(f"An antiderivative with respect to {var}; add a constant of integration, + C.", log_caveat))

    a, b = _parse(lower, max_length), _parse(upper, max_length)
    if a.has(var) or b.has(var):
        raise InputError(f"The bounds cannot contain the integration variable '{var}'.")
    result = sympy.integrate(expr, (var, a, b))
    where = f"Definite integral with respect to {var} from {pretty(str(a))} to {pretty(str(b))}."

    if result.has(sympy.Integral):
        return _not_established("Could not find an exact value for this integral.", NOT_AN_ANSWER)
    if result.has(sympy.nan, sympy.zoo):
        return _not_established(
            "The integral is undefined, diverges, or could not be evaluated.",
            "A common cause is a singularity of the integrand inside the interval, e.g. 1/x on [-1, 1]. " + NOT_AN_ANSWER,
        )
    if result in (sympy.oo, -sympy.oo):
        return _make(result, f"{where} The integral diverges ({'+' if result == sympy.oo else '-'}infinity).")
    complex_warning = None
    if result.is_number and abs(sympy.im(sympy.N(result))) > 1e-12:
        complex_warning = ("Warning: the result is complex. For a real-valued integral this usually means the "
                           "integrand is undefined or multi-valued (a branch cut) somewhere on the interval.")
    return _make(result, _join(where, complex_warning))


def limit(expression: str, point: str, variable: str | None = None, direction: str = "both", *,
          max_length: int = DEFAULT_MAX_LENGTH) -> MathResult:
    if direction not in ("both", "+", "-"):
        raise InputError("The direction must be 'both', '+' or '-'.")
    expr = _parse(expression, max_length)
    pt = _parse(point, max_length)
    var = _pick_variable_or_x(expr.free_symbols, variable)
    if pt.has(var):
        raise InputError(f"The limit point cannot contain the variable '{var}'.")

    at_infinity = pt in (sympy.oo, -sympy.oo)
    sides = ["+"] if at_infinity else (["+", "-"] if direction == "both" else [direction])
    results = {side: sympy.limit(expr, var, pt, side) for side in sides}
    for r in results.values():
        if r.has(sympy.Limit) or r.has(sympy.nan, sympy.zoo):
            return _not_established("Could not determine this limit.", NOT_AN_ANSWER)

    pt_text = pretty(str(pt))
    if at_infinity:
        label = f"Limit as {var} → {pt_text}." + (" (The direction is ignored at infinity.)" if direction != "both" else "")
    else:
        label = f"Limit as {var} → {pt_text}" + {"both": " (two-sided).", "+": " from the right.", "-": " from the left."}[direction]

    for r in results.values():
        if isinstance(r, sympy.AccumBounds):
            return MathResult(
                text=f"Does not exist: the values keep oscillating within [{r.min}, {r.max}] without settling.",
                note=label)
    if len(results) == 2:
        left, right = results["-"], results["+"]
        # Compare with == first: oo - oo is nan, so subtracting would wrongly report two infinite sides as different.
        same = left == right or (left.is_finite and right.is_finite and sympy.simplify(left - right) == 0)
        if not same:
            return MathResult(
                text=(f"Does not exist (two-sided): from the left the limit is {pretty(str(left))}, "
                      f"from the right it is {pretty(str(right))}."),
                note=label)
    value = next(iter(results.values()))
    if value in (sympy.oo, -sympy.oo):
        label += " The function grows without bound, so the limit is infinite rather than a finite number."
    return _make(value, label)


def evaluate(expression: str, digits: int = 15, *, max_length: int = DEFAULT_MAX_LENGTH) -> MathResult:
    if not isinstance(digits, int) or not 1 <= digits <= MAX_DIGITS:
        raise InputError(f"The number of digits must be between 1 and {MAX_DIGITS}.")
    expr = _parse(expression, max_length)
    if expr.free_symbols:
        names = ", ".join(sorted(str(s) for s in expr.free_symbols))
        raise InputError(f"This expression contains variables ({names}), so it has no single numerical value. "
                         "Use /simplify, or replace the variables with numbers.")
    if expr.is_Integer or not expr.is_finite:
        return MathResult(text=pretty(str(expr)), note="Exact value." if expr.is_Integer else None)
    return MathResult(text=str(sympy.N(expr, digits)), approximate_only=True,
                      note=f"Numerical approximation to {digits} significant digits.")


# ------------------------------------------------------------------------------------ matrices

def _matrix_input(text: str, max_length: int) -> sympy.Matrix:
    return to_sympy_matrix(validate_matrix(text, max_length))


def _size(M: sympy.Matrix) -> str:
    return f"{M.rows}×{M.cols}"


def _matrix_text(M: sympy.Matrix) -> str:
    """Plain text that can be pasted straight back into /matrix: [[1, 2], [3, 4]]."""
    return "[" + ", ".join("[" + ", ".join(pretty(str(e)) for e in M.row(i)) + "]" for i in range(M.rows)) + "]"


def _matrix_latex(M: sympy.Matrix) -> str:
    rows = [" & ".join(sympy.latex(e) for e in M.row(i)) for i in range(M.rows)]
    return r"\begin{bmatrix} " + r" \\ ".join(rows) + r" \end{bmatrix}"


def _make_matrix(M: sympy.Matrix, note: str | None = None) -> MathResult:
    if M.free_symbols:
        M = M.applyfunc(sympy.simplify)
    text = _matrix_text(M)
    if len(text) > MAX_RESULT_CHARS:
        return MathResult(text=text[:MAX_RESULT_CHARS] + "…", note=_join(note, "The result is too long to show in full."))
    latex = _matrix_latex(M)
    return MathResult(text=text, latex=latex if len(latex) <= MAX_LATEX_CHARS else None, note=note)


def _require_square(M: sympy.Matrix, what: str) -> None:
    if M.rows != M.cols:
        raise InputError(f"The {what} needs a square matrix, but this one is {_size(M)}.")


def _check_symbolic_size(*matrices: sympy.Matrix) -> None:
    for M in matrices:
        if M.free_symbols and max(M.shape) > MAX_SYMBOLIC_MATRIX_DIM:
            raise InputError(
                f"Matrices containing variables are limited to {MAX_SYMBOLIC_MATRIX_DIM}x{MAX_SYMBOLIC_MATRIX_DIM} "
                "(larger symbolic calculations take too long). Numeric matrices can be up to 6x6."
            )


_SYMBOLIC_CAVEAT = ("The matrix contains variables, so this holds for generic values of them; "
                    "special values can change the result.")


def _m_determinant(A: sympy.Matrix) -> MathResult:
    _require_square(A, "determinant")
    return _make(sympy.simplify(A.det()), f"Determinant of a {_size(A)} matrix.")


def _m_inverse(A: sympy.Matrix) -> MathResult:
    _require_square(A, "inverse")
    det = sympy.simplify(A.det())
    if det == 0:
        return MathResult(text="Not invertible: the determinant is 0 (the matrix is singular).",
                          note=f"Determinant of the {_size(A)} matrix is 0.")
    note = (f"Valid wherever the determinant, {pretty(str(det))}, is not 0." if A.free_symbols
            else f"Inverse of a {_size(A)} matrix; its determinant is {pretty(str(det))}.")
    return _make_matrix(A.inv(), note)


def _m_transpose(A: sympy.Matrix) -> MathResult:
    return _make_matrix(A.T, f"Transpose: a {_size(A)} matrix becomes {_size(A.T)}.")


def _m_trace(A: sympy.Matrix) -> MathResult:
    _require_square(A, "trace")
    return _make(sympy.simplify(A.trace()), "Trace: the sum of the diagonal entries.")


def _m_rank(A: sympy.Matrix) -> MathResult:
    note = _join(f"Rank of a {_size(A)} matrix.", _SYMBOLIC_CAVEAT if A.free_symbols else None)
    return MathResult(text=str(A.rank()), note=note)


def _m_rref(A: sympy.Matrix) -> MathResult:
    reduced, pivots = A.rref()
    cols = ", ".join(str(p + 1) for p in pivots) or "none"
    note = _join(f"Reduced row echelon form. Pivot columns: {cols}.", _SYMBOLIC_CAVEAT if A.free_symbols else None)
    return _make_matrix(reduced, note)


def _m_eigenvalues(A: sympy.Matrix) -> MathResult:
    """Eigenvalues via the characteristic polynomial, factored over the rationals.

    Factors of degree 1 and 2 give exact roots. Irreducible factors of degree 3 or more are shown as decimal
    approximations of the roots of that named polynomial: SymPy's own closed form for them is unreadable (a
    cubic with three real roots comes back as an expression full of complex numbers).
    """
    _require_square(A, "eigenvalues")
    lam = sympy.Symbol("lambda")
    poly = sympy.expand(A.charpoly(lam).as_expr())
    _, factors = sympy.factor_list(poly, lam)

    exact, approx, unresolved = [], [], []
    for factor, mult in factors:
        degree = sympy.degree(factor, lam)
        if degree == 0:
            continue
        if degree <= 2:
            exact += [(root, mult) for root in sympy.roots(factor, lam)]
        elif factor.free_symbols - {lam}:
            unresolved.append(factor)
        else:
            approx += [(sympy.N(r, 15), mult, factor) for r in sympy.Poly(factor, lam).nroots(n=15)]

    show = lambda e: pretty(str(e)).replace("lambda", "λ")  # noqa: E731
    if unresolved or sum(m for _, m in exact) + sum(m for _, m, _ in approx) != A.rows:
        extra = f" It has an irreducible factor of degree 3 or higher with variables: {show(unresolved[0])}." if unresolved else ""
        return _not_established("Could not find closed-form eigenvalues for this matrix.",
                                f"The eigenvalues are the roots of the characteristic polynomial.{extra} " + NOT_AN_ANSWER)

    def numeric_order(item):  # smallest real part first; fall back to SymPy's order for symbolic values
        value = item[0]
        if value.free_symbols:
            return (0.0, 0.0, sympy.default_sort_key(value))
        v = sympy.N(value)
        return (float(sympy.re(v)), float(sympy.im(v)), ())

    exact.sort(key=numeric_order)
    approx.sort(key=lambda item: (float(sympy.re(item[0])), float(sympy.im(item[0]))))
    texts, latexes, decimals = [], [], []
    for value, mult in exact:
        suffix = f" (multiplicity {mult})" if mult > 1 else ""
        texts.append(f"λ = {show(value)}{suffix}")
        latexes.append(rf"\lambda = {sympy.latex(value)}" + (rf"\;(\text{{multiplicity }}{mult})" if mult > 1 else ""))
        if (a := _approximation(value)):
            decimals.append(f"λ ≈ {a}")
    for value, mult, _factor in approx:
        suffix = f" (multiplicity {mult})" if mult > 1 else ""
        texts.append(f"λ ≈ {value}{suffix}")
        latexes.append(rf"\lambda \approx {sympy.latex(value)}" + (rf"\;(\text{{multiplicity }}{mult})" if mult > 1 else ""))

    note = "Eigenvalues over the complex numbers."
    if approx:
        polys = ", ".join(sorted({show(f) for _, _, f in approx}))
        note += (f" Values shown with ≈ are roots of the irreducible polynomial {polys} = 0, "
                 "which has no short exact form; they are decimal approximations.")
    return MathResult(text=", ".join(texts), latex=r",\;".join(latexes),
                      approximation=", ".join(decimals) or None, note=note)


_UNARY = {"determinant": _m_determinant, "inverse": _m_inverse, "transpose": _m_transpose, "trace": _m_trace,
          "rank": _m_rank, "rref": _m_rref, "eigenvalues": _m_eigenvalues}


def _m_binary(operation: str, A: sympy.Matrix, b: str, max_length: int) -> MathResult:
    if not b or not b.strip():
        raise InputError("This operation needs a second matrix B.")
    if not b.strip().startswith("["):
        if operation != "multiply":
            raise InputError("B must be a matrix such as [[1, 2], [3, 4]] for addition and subtraction.")
        _check_symbolic_size(A)
        return _make_matrix(A * _parse(b, max_length), "Every entry of A multiplied by the number or expression B.")
    B = _matrix_input(b, max_length)
    _check_symbolic_size(A, B)
    if operation in ("add", "subtract"):
        if A.shape != B.shape:
            verb = "add" if operation == "add" else "subtract"
            raise InputError(f"Cannot {verb} a {_size(A)} matrix and a {_size(B)} matrix: they must be the same size.")
        return _make_matrix(A + B if operation == "add" else A - B, f"{_size(A)} result.")
    if A.cols != B.rows:
        raise InputError(f"Cannot multiply a {_size(A)} matrix by a {_size(B)} matrix: the number of columns of A "
                         f"({A.cols}) must equal the number of rows of B ({B.rows}).")
    return _make_matrix(A * B, f"A ({_size(A)}) × B ({_size(B)}) gives a {_size(A * B)} result.")


def matrix(operation: str, a: str, b: str | None = None, *, max_length: int = DEFAULT_MAX_LENGTH) -> MathResult:
    if operation not in MATRIX_UNARY + MATRIX_BINARY:
        raise InputError(f"Unknown matrix operation {operation!r}.")
    A = _matrix_input(a, max_length)
    if operation in MATRIX_UNARY:
        if b:
            raise InputError("This operation uses only matrix A; leave B empty.")
        _check_symbolic_size(A)
        return _UNARY[operation](A)
    return _m_binary(operation, A, b, max_length)


def solve(equation: str, variable: str | None = None, domain: str = "real", *,
          max_length: int = DEFAULT_MAX_LENGTH) -> MathResult:
    if domain not in ("real", "complex"):
        raise InputError("The domain must be 'real' or 'complex'.")
    lhs_tree, rhs_tree = validate_equation(equation, max_length)
    f = to_sympy(lhs_tree) - to_sympy(rhs_tree)
    var = _pick_variable(f.free_symbols, variable)
    # Treat every other symbol as a real parameter; otherwise SymPy returns unhelpful results such as
    # Intersection({3 - x}, Reals) for "x + y = 3" solved for y.
    f = f.xreplace({s: sympy.Symbol(s.name, real=True) for s in f.free_symbols if s != var})
    dom, dom_name = (sympy.S.Reals, "real numbers") if domain == "real" else (sympy.S.Complexes, "complex numbers")
    note = f"Solutions over the {dom_name}."

    try:
        solutions = sympy.solveset(f, var, domain=dom)
    except NotImplementedError:
        solutions = None

    if solutions is None or isinstance(solutions, sympy.ConditionSet):
        return MathResult(
            text="Could not find the solutions exactly.", established=False,
            note="SymPy could not establish a closed-form solution set. This does NOT mean there are no solutions.",
        )
    if solutions == sympy.S.EmptySet:
        return MathResult(text=f"No solutions over the {dom_name}.", latex=r"\emptyset", note=note)
    if isinstance(solutions, sympy.FiniteSet):
        items = sorted(solutions, key=sympy.default_sort_key)
        text = ", ".join(f"{var} = {pretty(str(s))}" for s in items)
        latex = r",\;".join(f"{sympy.latex(var)} = {sympy.latex(s)}" for s in items)
        approx = [f"{var} ≈ {a}" for s in items if (a := _approximation(s))]
        return MathResult(text=text, latex=latex, approximation=", ".join(approx) or None, note=note)
    return MathResult(text=pretty(str(solutions)), latex=sympy.latex(solutions), note=note)


OPERATIONS = {
    "simplify": simplify, "factor": factor, "expand": expand, "diff": diff,
    "integrate": integrate, "limit": limit, "evaluate": evaluate, "solve": solve, "matrix": matrix,
}


def run(op: str, args: dict, max_length: int = DEFAULT_MAX_LENGTH) -> MathResult:
    func = OPERATIONS.get(op)
    if func is None:
        raise InputError(f"Unknown operation {op!r}.")
    return func(**args, max_length=max_length)
