"""Convert a *validated* AST into SymPy objects. Runs in the worker process only.

No eval()/sympify: each whitelisted node type is mapped to a SymPy operation explicitly.
"""
from __future__ import annotations

import ast

import sympy

from .errors import InputError

FUNCTIONS = {
    "sin": sympy.sin, "cos": sympy.cos, "tan": sympy.tan,
    "asin": sympy.asin, "acos": sympy.acos, "atan": sympy.atan,
    "sinh": sympy.sinh, "cosh": sympy.cosh, "tanh": sympy.tanh,
    "exp": sympy.exp, "log": sympy.log, "ln": sympy.log,
    "sqrt": sympy.sqrt, "abs": sympy.Abs,
}
CONSTANTS = {"pi": sympy.pi, "e": sympy.E, "oo": sympy.oo}


def to_sympy_matrix(rows) -> sympy.Matrix:
    """Convert the validated entries from ``validate_matrix`` into a SymPy Matrix."""
    return sympy.Matrix([[to_sympy(cell) for cell in row] for row in rows])


def to_sympy(node: ast.AST) -> sympy.Expr:
    expr = _convert(node)
    if expr.has(sympy.zoo, sympy.nan):
        raise InputError("That expression is undefined (for example, it divides by zero).")
    return expr


def _convert(node: ast.AST):
    if isinstance(node, ast.Expression):
        return _convert(node.body)
    if isinstance(node, ast.Constant):
        # Decimals become exact rationals (0.5 -> 1/2) so results stay exact.
        return sympy.Integer(node.value) if isinstance(node.value, int) else sympy.Rational(repr(node.value))
    if isinstance(node, ast.Name):
        return CONSTANTS.get(node.id) or sympy.Symbol(node.id)
    if isinstance(node, ast.UnaryOp):
        v = _convert(node.operand)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp):
        left, right = _convert(node.left), _convert(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        if isinstance(node.op, ast.Pow):
            return left**right
    if isinstance(node, ast.Call):
        return FUNCTIONS[node.func.id](*[_convert(a) for a in node.args])
    raise InputError("Unsupported expression.")  # unreachable after validation
