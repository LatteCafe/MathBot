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
COOLDOWN = dict(rate=1, per=3.0, key=lambda i: i.user.id)  # one calculation per user per 3 seconds
RESULT_LATEX_MAX = 1500  # results can be longer than what users are allowed to type into /latex


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
