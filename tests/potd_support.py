"""Shared helpers for the Problem of the Day tests."""
from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from math_engine import operations
from services.problem_bank import ProblemBank, parse_problems

UTC = timezone.utc
NOW = datetime(2026, 10, 19, 14, 0, tzinfo=UTC)      # 10:00 in Toronto (EDT, UTC-4)


def raw(id="p1", subject="analysis", level="core", answer="12", **over) -> dict:
    data = dict(id=id, subject=subject, level=level, title=f"Title {id}", statement="Compute the thing.",
                answer_type="value", answer=answer, hints=["first hint", "second hint"], solution="Because.")
    data.update(over)
    return data


def make_bank(*specs) -> ProblemBank:
    """Each spec is a raw dict, or an (id, subject, level) tuple."""
    items = [s if isinstance(s, dict) else raw(*s) for s in specs]
    return ProblemBank(parse_problems(items))


class InProcessEngine:
    """Same interface as MathEngine, but computes in-process (fast), with identical error behaviour."""

    async def run(self, op, **args):
        return operations.run(op, args)


class FailingEngine:
    def __init__(self, error):
        self.error = error

    async def run(self, op, **args):
        raise self.error


class FakeInteraction:
    """Just enough of discord.Interaction to drive the handlers and record what they send."""

    def __init__(self, user_id=1, message_id=None, guild_id=100, channel_id=500, guild=None):
        self.user = SimpleNamespace(id=user_id, display_name=f"user{user_id}")
        self.message = SimpleNamespace(id=message_id) if message_id is not None else None
        self.guild_id, self.channel_id, self.guild = guild_id, channel_id, guild
        self.sent, self.modals, self.edits, self._done = [], [], [], False
        outer = self

        class Response:
            async def defer(self, **kw):
                outer._done = True

            def is_done(self):
                return outer._done

            async def send_message(self, content=None, **kw):
                outer._done = True
                outer.sent.append((content, kw))

            async def send_modal(self, modal):
                outer._done = True
                outer.modals.append(modal)

            async def edit_message(self, **kw):
                outer._done = True
                outer.edits.append(kw)

        class Followup:
            async def send(self, content=None, **kw):
                outer.sent.append((content, kw))

        self.response, self.followup = Response(), Followup()

    @property
    def text(self) -> str:
        """All text sent so far, including embed titles and descriptions."""
        parts = []
        for content, kw in self.sent:
            parts.append(content or "")
            embed = kw.get("embed")
            if embed is not None:
                parts += [embed.title or "", embed.description or ""]
        return "\n".join(parts)
