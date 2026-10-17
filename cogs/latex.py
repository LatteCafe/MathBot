"""/latex: render a LaTeX math expression as an image."""
from __future__ import annotations

import io
import logging

import discord
from discord import app_commands
from discord.ext import commands

from math_engine.errors import ComputeFailed, ComputeTimeout, InputError
from rendering.renderer import LatexRenderer

from .formatting import clean_inline, format_error

log = logging.getLogger(__name__)


class Latex(commands.Cog):
    def __init__(self, renderer: LatexRenderer) -> None:
        self.renderer = renderer

    @app_commands.command(name="latex", description="Render a LaTeX math expression as an image")
    @app_commands.describe(expression=r"LaTeX math without $ signs, e.g. \frac{a}{b}, \int_0^1 x^2 dx, \begin{pmatrix}1&2\\3&4\end{pmatrix}")
    @app_commands.checks.cooldown(1, 3.0, key=lambda i: i.user.id)
    async def latex(self, interaction: discord.Interaction, expression: str) -> None:
        await interaction.response.defer(thinking=True)
        try:
            png = await self.renderer.render(expression)
        except InputError as exc:
            await interaction.followup.send(format_error("input", str(exc)))
        except ComputeTimeout as exc:
            await interaction.followup.send(format_error("timeout", str(exc)))
        except ComputeFailed as exc:
            await interaction.followup.send(format_error("failed", str(exc)))
        else:
            picture = discord.File(io.BytesIO(png), filename="latex.png", description=expression[:1000])
            await interaction.followup.send(f"`{clean_inline(expression)}`", file=picture)

    async def cog_app_command_error(self, interaction: discord.Interaction, error: app_commands.AppCommandError) -> None:
        if isinstance(error, app_commands.CommandOnCooldown):
            message = f"⏳ Slow down a little, try again in {error.retry_after:.1f}s."
        else:
            log.exception("Unhandled error in /latex", exc_info=error)
            message = "⚠️ Something went wrong on my side. It has been logged."
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Latex(bot.renderer))  # type: ignore[attr-defined]
