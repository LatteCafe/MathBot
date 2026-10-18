"""Symbolic calculator slash commands (thin layer: parse arguments, call the engine, format the reply)."""
from __future__ import annotations

import io
import logging
from typing import Literal, Optional

import discord
from discord import app_commands
from discord.ext import commands

from math_engine.engine import MathEngine
from math_engine.errors import ComputeFailed, ComputeTimeout, InputError, MathError
from rendering.renderer import LatexRenderer

from .formatting import format_error, format_result

log = logging.getLogger(__name__)
MATRIX_TITLES = {
    "determinant": "Determinant of", "inverse": "Inverse of", "transpose": "Transpose of", "trace": "Trace of",
    "rank": "Rank of", "rref": "Row-reduced form of", "eigenvalues": "Eigenvalues of",
    "add": "Sum:", "subtract": "Difference:", "multiply": "Product:",
}
MATRIX_SYMBOLS = {"add": "+", "subtract": "−", "multiply": "×"}
COOLDOWN = dict(rate=1, per=3.0, key=lambda i: i.user.id)  # one calculation per user per 3 seconds
RESULT_LATEX_MAX = 3000  # results can be longer than what users are allowed to type into /latex


class Calc(commands.Cog):
    def __init__(self, engine: MathEngine, renderer: LatexRenderer | None = None) -> None:
        self.engine = engine
        self.renderer = renderer  # None = text-only output

    async def _render_image(self, result) -> discord.File | None:
        """Typeset the result as an image. Any failure falls back to plain text; it never breaks the command."""
        if self.renderer is None or not result.established or not result.latex:
            return None
        try:
            png = await self.renderer.render(result.latex, max_length=RESULT_LATEX_MAX)
        except MathError as exc:
            log.warning("Could not render result as an image (%s); sending text. LaTeX: %.200r", exc, result.latex)
            return None
        return discord.File(io.BytesIO(png), filename="result.png", description=result.text[:1000])

    async def _run(self, interaction: discord.Interaction, op: str, title: str, query: str, **args) -> None:
        await interaction.response.defer(thinking=True)  # SymPy can take longer than Discord's 3-second window
        try:
            result = await self.engine.run(op, **args)
        except InputError as exc:
            await interaction.followup.send(format_error("input", str(exc)))
        except ComputeTimeout as exc:
            await interaction.followup.send(format_error("timeout", str(exc)))
        except ComputeFailed as exc:
            await interaction.followup.send(format_error("failed", str(exc)))
        else:
            picture = await self._render_image(result)
            kwargs = {"file": picture} if picture else {}
            await interaction.followup.send(format_result(title, query, result, has_image=picture is not None), **kwargs)

    @app_commands.command(name="simplify", description="Simplify an expression, e.g. (x^2 - 1)/(x - 1)")
    @app_commands.describe(expression="Expression using + - * / ^, parentheses, and functions like sin, cos, sqrt, log")
    @app_commands.checks.cooldown(**COOLDOWN)
    async def simplify(self, interaction: discord.Interaction, expression: str) -> None:
        await self._run(interaction, "simplify", "Simplify", expression, expression=expression)

    @app_commands.command(name="factor", description="Factor an expression over the rationals, e.g. x^2 - 1")
    @app_commands.describe(expression="Expression to factor, e.g. x^3 - 6x^2 + 11x - 6")
    @app_commands.checks.cooldown(**COOLDOWN)
    async def factor(self, interaction: discord.Interaction, expression: str) -> None:
        await self._run(interaction, "factor", "Factor", expression, expression=expression)

    @app_commands.command(name="expand", description="Expand an expression, e.g. (x + 1)^3")
    @app_commands.describe(expression="Expression to expand, e.g. (x+1)(x-1)")
    @app_commands.checks.cooldown(**COOLDOWN)
    async def expand(self, interaction: discord.Interaction, expression: str) -> None:
        await self._run(interaction, "expand", "Expand", expression, expression=expression)

    @app_commands.command(name="diff", description="Differentiate an expression, e.g. x^3 * sin(x)")
    @app_commands.describe(
        expression="The expression to differentiate",
        variable="Variable to differentiate by (optional if the expression has only one)",
        order="Derivative order, 1 to 5 (default 1)",
    )
    @app_commands.checks.cooldown(**COOLDOWN)
    async def diff(self, interaction: discord.Interaction, expression: str,
                   variable: Optional[str] = None, order: app_commands.Range[int, 1, 5] = 1) -> None:
        await self._run(interaction, "diff", "Derivative of", expression,
                        expression=expression, variable=variable, order=order)

    @app_commands.command(name="integrate", description="Integrate an expression (add bounds for a definite integral)")
    @app_commands.describe(
        expression="The integrand, e.g. x^2 or exp(-x^2)",
        variable="Variable to integrate by (optional if there is only one)",
        lower="Lower bound for a definite integral, e.g. 0 or -oo",
        upper="Upper bound for a definite integral, e.g. 1, pi or oo (oo = infinity)",
    )
    @app_commands.checks.cooldown(**COOLDOWN)
    async def integrate(self, interaction: discord.Interaction, expression: str, variable: Optional[str] = None,
                        lower: Optional[str] = None, upper: Optional[str] = None) -> None:
        query = f"{expression}  from {lower} to {upper}" if lower and upper else expression
        await self._run(interaction, "integrate", "Integral of", query,
                        expression=expression, variable=variable, lower=lower, upper=upper)

    @app_commands.command(name="limit", description="Find a limit, e.g. sin(x)/x as x approaches 0")
    @app_commands.describe(
        expression="The expression, e.g. sin(x)/x",
        point="The value the variable approaches, e.g. 0, pi or oo (oo = infinity)",
        variable="Variable (optional if there is only one)",
        direction="Approach from both sides (default), the right, or the left",
    )
    @app_commands.choices(direction=[
        app_commands.Choice(name="both sides (default)", value="both"),
        app_commands.Choice(name="from the right (x → a⁺)", value="+"),
        app_commands.Choice(name="from the left (x → a⁻)", value="-"),
    ])
    @app_commands.checks.cooldown(**COOLDOWN)
    async def limit(self, interaction: discord.Interaction, expression: str, point: str,
                    variable: Optional[str] = None, direction: str = "both") -> None:
        await self._run(interaction, "limit", "Limit of", expression,
                        expression=expression, point=point, variable=variable, direction=direction)

    @app_commands.command(name="evaluate", description="Numerically evaluate a constant expression, e.g. sqrt(2) + pi")
    @app_commands.describe(expression="An expression with no variables, e.g. pi*e or sqrt(2)",
                           digits="Significant digits, 1 to 50 (default 15)")
    @app_commands.checks.cooldown(**COOLDOWN)
    async def evaluate(self, interaction: discord.Interaction, expression: str,
                       digits: app_commands.Range[int, 1, 50] = 15) -> None:
        await self._run(interaction, "evaluate", "Evaluate", expression, expression=expression, digits=digits)

    @app_commands.command(name="matrix", description="Matrix operations, e.g. the determinant of [[1,2],[3,4]]")
    @app_commands.describe(
        operation="What to compute",
        a="Matrix A as rows in brackets, e.g. [[1,2],[3,4]]. Entries can contain variables (up to 4x4).",
        b="Matrix B (or a plain number, for multiply) for add, subtract and multiply",
    )
    @app_commands.choices(operation=[
        app_commands.Choice(name="determinant", value="determinant"),
        app_commands.Choice(name="inverse", value="inverse"),
        app_commands.Choice(name="transpose", value="transpose"),
        app_commands.Choice(name="trace", value="trace"),
        app_commands.Choice(name="rank", value="rank"),
        app_commands.Choice(name="row-reduced form (rref)", value="rref"),
        app_commands.Choice(name="eigenvalues", value="eigenvalues"),
        app_commands.Choice(name="add: A + B", value="add"),
        app_commands.Choice(name="subtract: A − B", value="subtract"),
        app_commands.Choice(name="multiply: A × B (B may be a number)", value="multiply"),
    ])
    @app_commands.checks.cooldown(**COOLDOWN)
    async def matrix(self, interaction: discord.Interaction, operation: str, a: str, b: Optional[str] = None) -> None:
        query = f"{a} {MATRIX_SYMBOLS[operation]} {b}" if operation in MATRIX_SYMBOLS and b else a
        await self._run(interaction, "matrix", MATRIX_TITLES.get(operation, "Matrix"), query,
                        operation=operation, a=a, b=b)

    @app_commands.command(name="solve", description="Solve an equation, e.g. x^2 - 4 = 0")
    @app_commands.describe(
        equation="An equation like x^2 = 4 (without '=', it is solved as expression = 0)",
        variable="Variable to solve for (optional if there is only one)",
        domain="Look for real solutions (default) or complex solutions",
    )
    @app_commands.checks.cooldown(**COOLDOWN)
    async def solve(self, interaction: discord.Interaction, equation: str,
                    variable: Optional[str] = None, domain: Literal["real", "complex"] = "real") -> None:
        await self._run(interaction, "solve", "Solve", equation, equation=equation, variable=variable, domain=domain)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            message = f"⏳ Slow down a little, try again in {error.retry_after:.1f}s."
        else:
            log.exception("Unhandled error in /%s", interaction.command.name if interaction.command else "?", exc_info=error)
            message = "⚠️ Something went wrong on my side. It has been logged."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Calc(bot.engine, bot.renderer))  # type: ignore[attr-defined]
