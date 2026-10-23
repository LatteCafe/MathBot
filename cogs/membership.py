"""Helpers for the most common setup problem: the bot was added without the `bot` scope, so it is not a real
member of the server (no role to grant permissions to, not in the member list, cannot see private channels)."""
from __future__ import annotations

import discord

INVITE_SCOPES = ("bot", "applications.commands")
INVITE_PERMISSIONS = discord.Permissions(view_channel=True, send_messages=True, embed_links=True, attach_files=True)
REQUIRED_CHANNEL_PERMISSIONS = {
    "view_channel": "View Channel", "send_messages": "Send Messages", "embed_links": "Embed Links",
    "attach_files": "Attach Files",
}


def invite_url(client_id: int | None) -> str | None:
    """The link that adds the bot as a real server member with exactly the permissions it needs."""
    if not client_id:
        return None
    return discord.utils.oauth_url(client_id, permissions=INVITE_PERMISSIONS, scopes=INVITE_SCOPES)


def is_member(guild) -> bool:
    """True if the bot is a member of `guild`. For an app installed without the `bot` scope, discord.py has no member
    object for the bot (guild.me is None), even though slash commands still work."""
    return guild is not None and getattr(guild, "me", None) is not None


def missing_permissions(channel, guild) -> list[str]:
    """Names of the permissions the bot lacks in `channel` (empty if it has them all, or if it cannot be determined)."""
    me = getattr(guild if guild is not None else getattr(channel, "guild", None), "me", None)
    if me is None or not hasattr(channel, "permissions_for"):
        return []
    perms = channel.permissions_for(me)
    return [label for attr, label in REQUIRED_CHANNEL_PERMISSIONS.items() if not getattr(perms, attr, True)]


def not_a_member_message(client_id: int | None) -> str:
    link = invite_url(client_id)
    how = f"Re-add me with this link: {link}" if link else "Use the `/invite` command to get the correct link."
    return ("⚠️ **I am not a member of this server.** I was added without the `bot` permission scope, so I can answer "
            "slash commands but I have no role to give permissions to, I do not appear in the member list, and I cannot "
            f"post in private channels.\n{how}\n*(Authorising it again adds me as a proper member; nothing is lost.)*")
