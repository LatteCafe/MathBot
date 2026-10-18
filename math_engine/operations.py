"""SymPy operations. Runs in the worker process only (the bot process never imports this).

Principle: never present a result as established when it is not. SymPy signals trouble in several ways
(an unevaluated Integral/Limit, ``nan``, ``zoo``); each is turned into an explicit "not established" result.
"""
from __future__ import annotations

import sympy

from .convert import to_sympy
from .errors import InputError
from .results import MathResult
from .validate import DEFAULT_MAX_LENGTH, validate_equation, validate_expression, validate_variable

MAX_DERIVATIVE_ORDER = 5
MAX_DIGITS = 50
MAX_RESULT_CHARS = 4000   # longer results are truncated (and not typeset)
MAX_LATEX_CHARS = 3000
NOT_AN_ANSWER = "That does NOT mean there is no answer, only that SymPy could not establish one."


def pretty(text: str) -> str:
    """SymPy prints powers as ``**``; show ``^`` which is what users type."""
    return text.replace("**", "^")


def _approximation(expr) -> str | None:
    """A decimal approximation, only for exact irrational/complex numbers (where it adds information)."""
    if expr.is_number and not expr.is_Rational and expr.is_finite:
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
    "integrate": integrate, "limit": limit, "evaluate": evaluate, "solve": solve,
}


def run(op: str, args: dict, max_length: int = DEFAULT_MAX_LENGTH) -> MathResult:
    func = OPERATIONS.get(op)
    if func is None:
        raise InputError(f"Unknown operation {op!r}.")
    return func(**args, max_length=max_length)
