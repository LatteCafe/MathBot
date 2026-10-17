"""SymPy operations. Runs in the worker process only (the bot process never imports this)."""
from __future__ import annotations

import sympy

from .convert import to_sympy
from .errors import InputError
from .results import MathResult
from .validate import DEFAULT_MAX_LENGTH, validate_equation, validate_expression, validate_variable

MAX_DERIVATIVE_ORDER = 5


def pretty(text: str) -> str:
    """SymPy prints powers as ``**``; show ``^`` which is what users type."""
    return text.replace("**", "^")


def _approximation(expr) -> str | None:
    """A decimal approximation, only for exact irrational/complex numbers (where it adds information)."""
    if expr.is_number and not expr.is_Rational and expr.is_finite:
        return str(sympy.N(expr, 15))
    return None


def _pick_variable(free: set, requested: str | None, *, allow_absent: bool = False) -> sympy.Symbol:
    if requested:
        symbol = sympy.Symbol(validate_variable(requested))
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


def simplify(expression: str, *, max_length: int = DEFAULT_MAX_LENGTH) -> MathResult:
    expr = to_sympy(validate_expression(expression, max_length)[1])
    result = sympy.simplify(expr)
    return MathResult(text=pretty(str(result)), latex=sympy.latex(result), approximation=_approximation(result))


def diff(expression: str, variable: str | None = None, order: int = 1, *,
         max_length: int = DEFAULT_MAX_LENGTH) -> MathResult:
    if not isinstance(order, int) or not 1 <= order <= MAX_DERIVATIVE_ORDER:
        raise InputError(f"The derivative order must be between 1 and {MAX_DERIVATIVE_ORDER}.")
    expr = to_sympy(validate_expression(expression, max_length)[1])
    var = _pick_variable(expr.free_symbols, variable, allow_absent=not expr.free_symbols)
    result = sympy.simplify(sympy.diff(expr, var, order))
    return MathResult(
        text=pretty(str(result)), latex=sympy.latex(result), approximation=_approximation(result),
        note=f"Derivative of order {order} with respect to {var}.",
    )


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


OPERATIONS = {"simplify": simplify, "diff": diff, "solve": solve}


def run(op: str, args: dict, max_length: int = DEFAULT_MAX_LENGTH) -> MathResult:
    func = OPERATIONS.get(op)
    if func is None:
        raise InputError(f"Unknown operation {op!r}.")
    return func(**args, max_length=max_length)
