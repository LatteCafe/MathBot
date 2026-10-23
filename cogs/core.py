"""Basic housekeeping commands."""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from .membership import invite_url


class Core(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="ping", description="Check that the bot is alive")
    async def ping(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(f"🏓 Pong! {self.bot.latency * 1000:.0f} ms", ephemeral=True)


    @app_commands.command(name="invite", description="Get the link that adds me to a server as a proper member")
    async def invite(self, interaction: discord.Interaction) -> None:
        url = invite_url(self.bot.application_id or getattr(self.bot.user, "id", None))
        if url is None:
            await interaction.response.send_message("I am not fully started yet; try again in a moment.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"**Add me to a server:** {url}\n"
            "This adds me as a real member with a role (so you can control which channels I can use) and with the "
            "permissions I need: View Channels, Send Messages, Embed Links and Attach Files. "
            "For a private channel, also allow my role to view that channel.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Core(bot))
