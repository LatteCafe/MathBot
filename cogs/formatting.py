"""Turn engine results into Discord message text. Pure functions, easy to test."""
from __future__ import annotations

from math_engine.results import MathResult

MAX_MESSAGE = 1900   # Discord's limit is 2000 characters per message
MAX_COPYABLE = 150   # longest plain-text result shown next to the image
INLINE_RESULT_CHARS = 600   # a longer result is not dumped into the chat: it gets a summary and an attached file
RESULT_FILENAME = "result.txt"


def is_overflow(result: MathResult) -> bool:
    """Is the result too large to show inline?"""
    return result.established and (len(result.text) > INLINE_RESULT_CHARS or result.truncated)


def attachment_text(result: MathResult) -> str | None:
    """The complete result as text for a file attachment, or None if there is nothing complete to attach."""
    if not is_overflow(result) or result.truncated:
        return None
    return result.text + "\n"


def clean_inline(text: str, limit: int = 200) -> str:
    """Make user-supplied text safe to show inside inline code."""
    text = text.replace("`", "'").replace("\n", " ").strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def format_result(title: str, query: str, result: MathResult, *, has_image: bool = False,
                  has_attachment: bool = False) -> str:
    """``has_image``: the exact result is shown as a rendered image attached to the message.
    ``has_attachment``: the complete (oversized) result is attached as a text file."""
    lines = [f"**{title}** `{clean_inline(query)}`"]
    if not result.established:
        lines.append(f"⚠️ **Not established:** {result.text}")
    elif is_overflow(result):
        size = f" Summary: {result.summary}." if result.summary else f" It is {len(result.text):,} characters long."
        lines.append("⚠️ **The result is too large to display here.**" + size)
        if has_attachment:
            lines.append(f"📎 The complete result is attached as `{RESULT_FILENAME}`.")
        elif result.truncated:
            lines.append("It is too long to attach in full.")
    elif result.approximate_only:
        lines.append(f"**Approximate value:** `{clean_inline(result.text, 300)}`")
    elif has_image:
        if len(result.text) <= MAX_COPYABLE:
            lines.append(f"**Exact result** (plain text): `{clean_inline(result.text, MAX_COPYABLE)}`")
        else:
            lines.append("**Exact result:** (see image)")
    else:
        lines.append(f"**Exact result:**\n```\n{clean_inline(result.text, INLINE_RESULT_CHARS)}\n```")
        if result.summary:
            lines.append(f"*Summary: {result.summary}.*")
    if result.approximation and not result.approximate_only:
        lines.append(f"**Approximate (decimal):** `{clean_inline(result.approximation, 300)}`")
    if result.note:
        lines.append(f"*{result.note}*")
    message = "\n".join(lines)
    return message if len(message) <= MAX_MESSAGE else message[: MAX_MESSAGE - 1] + "…"


def format_error(kind: str, message: str) -> str:
    icon = {"input": "❌", "timeout": "⏱️", "failed": "⚠️"}.get(kind, "⚠️")
    return f"{icon} {clean_inline(message, 500)}"
