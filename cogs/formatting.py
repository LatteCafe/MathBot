"""Turn engine results into Discord message text. Pure functions, easy to test."""
from __future__ import annotations

from math_engine.results import MathResult

MAX_MESSAGE = 1900   # Discord's limit is 2000 characters per message
MAX_COPYABLE = 150   # longest plain-text result shown next to the image


def clean_inline(text: str, limit: int = 200) -> str:
    """Make user-supplied text safe to show inside inline code."""
    text = text.replace("`", "'").replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def format_result(title: str, query: str, result: MathResult, *, has_image: bool = False) -> str:
    """``has_image``: the exact result is shown as a rendered image attached to the message."""
    lines = [f"**{title}** `{clean_inline(query)}`"]
    if not result.established:
        lines.append(f"⚠️ **Not established:** {result.text}")
    elif has_image:
        if len(result.text) <= MAX_COPYABLE:
            lines.append(f"**Exact result** (plain text): `{clean_inline(result.text, MAX_COPYABLE)}`")
        else:
            lines.append("**Exact result:** (see image)")
    else:
        lines.append(f"**Exact result:**\n```\n{clean_inline(result.text, 1200)}\n```")
    if result.established and result.approximation:
        lines.append(f"**Approximate (decimal):** `{clean_inline(result.approximation, 300)}`")
    if result.note:
        lines.append(f"*{result.note}*")
    message = "\n".join(lines)
    return message if len(message) <= MAX_MESSAGE else message[: MAX_MESSAGE - 1] + "…"


def format_error(kind: str, message: str) -> str:
    icon = {"input": "❌", "timeout": "⏱️", "failed": "⚠️"}.get(kind, "⚠️")
    return f"{icon} {clean_inline(message, 500)}"
