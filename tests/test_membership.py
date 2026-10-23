"""The 'bot is not a real server member' problem: detection, the invite link, and clear diagnoses."""
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from cogs.core import Core
from cogs.membership import (INVITE_PERMISSIONS, invite_url, is_member, missing_permissions, not_a_member_message)
from tests.potd_support import FakeInteraction


def parts(url):
    parsed = urlparse(url)
    return parsed.netloc, parsed.path, {k: v[0] for k, v in parse_qs(parsed.query).items()}


def test_the_invite_link_adds_a_real_member_with_exactly_the_needed_permissions():
    host, path, query = parts(invite_url(123456789))
    assert host == "discord.com" and path == "/oauth2/authorize"
    assert query["client_id"] == "123456789"
    assert set(query["scope"].split()) == {"bot", "applications.commands"}      # the `bot` scope is what makes it a member
    assert int(query["permissions"]) == INVITE_PERMISSIONS.value == 1024 + 2048 + 16384 + 32768
    for name in ("view_channel", "send_messages", "embed_links", "attach_files"):
        assert getattr(INVITE_PERMISSIONS, name)
    assert not INVITE_PERMISSIONS.administrator and not INVITE_PERMISSIONS.manage_guild      # least privilege


def test_no_invite_link_without_a_client_id():
    assert invite_url(None) is None and invite_url(0) is None


def test_membership_detection():
    assert is_member(SimpleNamespace(me=object()))
    assert not is_member(SimpleNamespace(me=None))                  # discord.py has no member for a non-member app
    assert not is_member(None)


def channel_with(**perms):
    allowed = {"view_channel": True, "send_messages": True, "embed_links": True, "attach_files": True, **perms}
    return SimpleNamespace(permissions_for=lambda me: SimpleNamespace(**allowed))


def test_missing_permissions_are_named():
    guild = SimpleNamespace(me=object())
    assert missing_permissions(channel_with(), guild) == []
    assert missing_permissions(channel_with(embed_links=False, attach_files=False), guild) == ["Embed Links", "Attach Files"]
    assert missing_permissions(channel_with(view_channel=False), guild) == ["View Channel"]


def test_missing_permissions_cannot_be_judged_without_a_member():
    assert missing_permissions(channel_with(send_messages=False), SimpleNamespace(me=None)) == []
    assert missing_permissions(channel_with(send_messages=False), None) == []
    assert missing_permissions(None, SimpleNamespace(me=object())) == []


def test_the_channels_own_guild_is_used_when_none_is_given():
    channel = channel_with(send_messages=False)
    channel.guild = SimpleNamespace(me=object())
    assert missing_permissions(channel, None) == ["Send Messages"]


def test_the_not_a_member_message_explains_the_cause_and_gives_the_fix():
    with_link = not_a_member_message(777)
    assert "not a member" in with_link and "bot` permission scope" in with_link and "client_id=777" in with_link
    assert "private channels" in with_link and "member list" in with_link
    without_link = not_a_member_message(None)
    assert "/invite" in without_link and "http" not in without_link


# ------------------------------------------------------------------------------------------ the /invite command

async def test_the_invite_command_replies_privately_with_the_link():
    bot = SimpleNamespace(application_id=555, user=SimpleNamespace(id=555))
    core = Core(bot)
    i = FakeInteraction()
    await core.invite.callback(core, i)
    content, kwargs = i.sent[0]
    assert kwargs["ephemeral"] is True and "client_id=555" in content and "permissions=52224" in content
    assert "role" in content and "private channel" in content


async def test_the_invite_command_falls_back_to_the_user_id_and_handles_not_ready():
    core = Core(SimpleNamespace(application_id=None, user=SimpleNamespace(id=999)))
    i = FakeInteraction()
    await core.invite.callback(core, i)
    assert "client_id=999" in i.sent[0][0]
    not_ready = Core(SimpleNamespace(application_id=None, user=None))
    j = FakeInteraction()
    await not_ready.invite.callback(not_ready, j)
    assert "not fully started" in j.sent[0][0]
