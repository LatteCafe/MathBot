"""Validation and normalisation of user-typed maths. Standard library only.

This module is the safety gate for user input. Design rules:

* User text is NEVER passed to eval(), exec(), or sympify(). It is parsed into a Python AST
  (parsing does not execute anything) and only a small whitelist of node types is allowed.
  The worker process then converts the validated AST to SymPy objects itself.
* Nothing here imports SymPy, so the bot process never has to load it.
* Power expressions are bounded so that things like 9^9^9 are rejected up front.
  The worker's timeout and memory limit remain the final safety net.
"""
from __future__ import annotations

import ast
import math
import re
from fractions import Fraction

from .errors import InputError

DEFAULT_MAX_LENGTH = 200
MAX_NODES = 120
MAX_NUMBER = 10**12        # largest literal accepted
MAX_EXPONENT = 1000        # largest numeric exponent accepted
MAX_RESULT_BITS = 20_000   # largest constant power result we allow SymPy to compute

ALLOWED_FUNCTIONS = frozenset(
    {"sin", "cos", "tan", "asin", "acos", "atan", "sinh", "cosh", "tanh",
     "exp", "log", "ln", "sqrt", "abs"}
)
CONSTANT_NAMES = frozenset({"pi", "e", "oo"})
# Functions we are willing to evaluate when bounding a constant exponent.
_BOUNDABLE_FUNCTIONS = frozenset({"sqrt", "abs", "sin", "cos"})

_ALLOWED_CHARS = re.compile(r"^[A-Za-z0-9+\-*/().,\s]*$")
_BIN_OPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Pow)
_UNARY_OPS = (ast.UAdd, ast.USub)

# Which arguments of each operation are expressions: (required, optional). Used by the bot process to
# reject bad input before spawning a worker.
OPERATION_ARGS = {
    "simplify": (("expression",), ()),
    "factor": (("expression",), ()),
    "expand": (("expression",), ()),
    "diff": (("expression",), ()),
    "integrate": (("expression",), ("lower", "upper")),
    "limit": (("expression", "point"), ()),
    "evaluate": (("expression",), ()),
}
EQUATION_ARGS = {"solve": ("equation",)}


def normalize(text: str) -> str:
    """Turn friendly notation into parseable Python-style syntax (``2x`` -> ``2*x``, ``^`` -> ``**``)."""
    s = text.strip()
    for old, new in (("−", "-"), ("×", "*"), ("·", "*"), ("÷", "/"), ("^", "**")):
        s = s.replace(old, new)
    s = re.sub(r"(?<![\w.])(\d+(?:\.\d+)?)\s*(?=[A-Za-z(])", r"\1*", s)   # 2x, 3(x+1), 2sin(x)
    s = re.sub(r"\)\s*(?=[A-Za-z0-9(])", ")*", s)                           # (x+1)(x-1), (x)y
    s = re.sub(r"(?<![A-Za-z0-9_])([A-Za-z])\s*(?=\()", r"\1*", s)          # x(x+1)
    return s


def validate_expression(text: str, max_length: int = DEFAULT_MAX_LENGTH) -> tuple[str, ast.Expression]:
    """Validate one expression. Returns (normalised text, AST). Raises InputError if unsafe/invalid."""
    if not isinstance(text, str) or not text.strip():
        raise InputError("The expression is empty.")
    if len(text) > max_length:
        raise InputError(f"The expression is too long ({len(text)} characters; the limit is {max_length}).")
    s = normalize(text)
    bad = next((c for c in s if not _ALLOWED_CHARS.match(c)), None)
    if bad is not None:
        raise InputError(f"Unsupported character {bad!r}. Use numbers, letters, + - * / ^, parentheses and commas.")
    try:
        tree = ast.parse(s, mode="eval")
    except (SyntaxError, ValueError, RecursionError, MemoryError):
        raise InputError("Could not parse that expression. Check for unbalanced parentheses or a missing operand.") from None
    if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
        raise InputError("The expression is too complex.")
    _check(tree)
    return s, tree


def split_equation(text: str) -> tuple[str, str]:
    """Split ``lhs = rhs`` into two strings. A bare expression means ``expr = 0``."""
    s = text.replace("==", "=")
    if s.count("=") > 1:
        raise InputError("Use at most one '=' sign in an equation.")
    if "=" in s:
        lhs, rhs = s.split("=", 1)
        if not lhs.strip() or not rhs.strip():
            raise InputError("Both sides of the equation need an expression.")
        return lhs, rhs
    return s, "0"


def validate_equation(text: str, max_length: int = DEFAULT_MAX_LENGTH):
    if isinstance(text, str) and len(text) > max_length:
        raise InputError(f"The equation is too long ({len(text)} characters; the limit is {max_length}).")
    lhs, rhs = split_equation(text)
    return validate_expression(lhs, max_length)[1], validate_expression(rhs, max_length)[1]


def validate_variable(name: str) -> str:
    if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z]", name.strip()) or name.strip() == "e":
        raise InputError("The variable must be a single letter (other than 'e', which is Euler's number).")
    return name.strip()


def check_inputs(op: str, args: dict, max_length: int = DEFAULT_MAX_LENGTH) -> None:
    """Cheap pre-check run in the bot process so invalid input never spawns a worker."""
    if op in OPERATION_ARGS:
        required, optional = OPERATION_ARGS[op]
        for key in required:
            validate_expression(args.get(key, ""), max_length)
        for key in optional:
            if args.get(key):
                validate_expression(args[key], max_length)
        if op == "integrate" and bool(args.get("lower")) != bool(args.get("upper")):
            raise InputError("Give both a lower and an upper bound, or neither (for an indefinite integral).")
    elif op in EQUATION_ARGS:
        validate_equation(args.get("equation", ""), max_length)
    else:
        raise InputError(f"Unknown operation {op!r}.")
    if args.get("variable"):
        validate_variable(args["variable"])


# --------------------------------------------------------------------------- AST whitelist

def _check(node: ast.AST) -> None:
    if isinstance(node, ast.Expression):
        _check(node.body)
    elif isinstance(node, ast.BinOp):
        if not isinstance(node.op, _BIN_OPS):
            raise InputError("That operator is not supported. Use + - * / and ^ for powers.")
        if isinstance(node.op, ast.Pow):
            _check_power(node)
        _check(node.left)
        _check(node.right)
    elif isinstance(node, ast.UnaryOp):
        if not isinstance(node.op, _UNARY_OPS):
            raise InputError("That operator is not supported.")
        _check(node.operand)
    elif isinstance(node, ast.Constant):
        value = node.value
        if type(value) not in (int, float):
            raise InputError("Only numbers are allowed as literals.")
        if abs(value) > MAX_NUMBER:
            raise InputError(f"Numbers larger than {MAX_NUMBER:,} are not supported.")
    elif isinstance(node, ast.Name):
        if node.id not in CONSTANT_NAMES and not re.fullmatch(r"[A-Za-z]", node.id):
            raise InputError(
                f"Unknown name {node.id!r}. Variables must be single letters; "
                "write products explicitly, e.g. x*y instead of xy."
            )
    elif isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name) or node.func.id not in ALLOWED_FUNCTIONS:
            name = node.func.id if isinstance(node.func, ast.Name) else "?"
            raise InputError(f"Unknown function {name!r}. Supported: {', '.join(sorted(ALLOWED_FUNCTIONS))}.")
        if node.keywords or not 1 <= len(node.args) <= 2:
            raise InputError(f"Wrong number of arguments for {node.func.id}().")
        for arg in node.args:
            _check(arg)
    else:
        raise InputError(f"Unsupported syntax in expression ({type(node).__name__}).")


def _has_variable(node: ast.AST) -> bool:
    return any(isinstance(n, ast.Name) and n.id not in CONSTANT_NAMES for n in ast.walk(node))


def _check_power(node: ast.BinOp) -> None:
    """Bound constant powers so SymPy is never asked to build astronomically large numbers."""
    if not _has_variable(node.right):
        if abs(_bound(node.right)) > MAX_EXPONENT:
            raise InputError(f"Exponents larger than {MAX_EXPONENT} are not supported.")
    if not _has_variable(node):
        _bound(node)


def _bound(node: ast.AST) -> Fraction:
    """Evaluate a variable-free expression approximately and safely, refusing anything huge."""
    if isinstance(node, ast.Constant):
        return Fraction(str(node.value))
    if isinstance(node, ast.Name):
        if node.id == "oo":
            raise InputError("Infinity cannot be used in an exponent.")
        return Fraction(4) if node.id == "pi" else Fraction(3)  # upper bounds for pi and e
    if isinstance(node, ast.UnaryOp):
        v = _bound(node.operand)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.Call):
        if node.func.id not in _BOUNDABLE_FUNCTIONS:
            raise InputError(f"{node.func.id}() is not supported inside a constant exponent.")
        v = _bound(node.args[0])
        return {"sqrt": max(abs(v), Fraction(1)), "abs": abs(v)}.get(node.func.id, Fraction(1))
    if isinstance(node, ast.BinOp):
        a, b = _bound(node.left), _bound(node.right)
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Mult):
            return a * b
        if isinstance(node.op, ast.Div):
            if b == 0:
                raise InputError("Division by zero.")
            return a / b
        if isinstance(node.op, ast.Pow):
            return _bound_pow(a, b)
    raise InputError("That constant expression is not supported inside an exponent.")


def _bound_pow(base: Fraction, exp: Fraction) -> Fraction:
    if base == 0:
        if exp < 0:
            raise InputError("Division by zero.")
        return Fraction(0)
    if exp.denominator == 1:
        n = abs(exp.numerator)
        size = max(base.numerator.bit_length(), base.denominator.bit_length(), 1)
        if n > MAX_EXPONENT or size * n > MAX_RESULT_BITS:
            raise InputError("That power is too large to compute.")
        return base**exp.numerator
    # Non-integer exponent: only the magnitude matters, so use floats.
    try:
        magnitude = abs(float(base)) ** float(exp)
    except (OverflowError, ZeroDivisionError):
        raise InputError("That power is too large to compute.") from None
    if not math.isfinite(magnitude) or magnitude > 10**MAX_EXPONENT:
        raise InputError("That power is too large to compute.")
    return Fraction(magnitude)
