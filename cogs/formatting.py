"""Turn engine results into Discord message text. Pure functions, easy to test."""
from __future__ import annotations

from math_engine.results import MathResult

MAX_MESSAGE = 1900   # Discord's limit is 2000 characters per message


def _clean(text: str, limit: int = 200) -> str:
    """Make user-supplied text safe to show inside inline code."""
    text = text.replace("`", "'").replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def format_result(title: str, query: str, result: MathResult) -> str:
    lines = [f"**{title}** `{_clean(query)}`"]
    if not result.established:
        lines.append(f"⚠️ **Not established:** {result.text}")
    else:
        body = _clean(result.text, 1200)
        lines.append(f"**Exact result:**\n```\n{body}\n```")
        if result.approximation:
            lines.append(f"**Approximate (decimal):** `{_clean(result.approximation, 300)}`")
    if result.note:
        lines.append(f"*{result.note}*")
    message = "\n".join(lines)
    return message if len(message) <= MAX_MESSAGE else message[: MAX_MESSAGE - 1] + "…"


def format_error(kind: str, message: str) -> str:
    icon = {"input": "❌", "timeout": "⏱️", "failed": "⚠️"}.get(kind, "⚠️")
    return f"{icon} {_clean(message, 500)}"
