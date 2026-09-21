"""Assistant conversation transcript (TUI-UX-01).

Presentation-only and **ephemeral**.  The transcript is an ordered in-memory
list of accepted turns owned by the assistant workspace widget.  It is:

- never persisted to the Vault and never canonical campaign state;
- populated only by accepted presentation actions (a submission that actually
  acquired the exclusive execution path) and by their terminal outcomes;
- rendered as plain text: untrusted model output is never interpreted as Rich
  markup;
- free of hidden reasoning / chain-of-thought: it only ever carries the
  user-facing ``AgentTextOutcome.message`` and the bounded presentation hint.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

__all__ = [
    "TranscriptEntry",
    "TranscriptRole",
    "TranscriptView",
]

_BODY_ID = "assistant-transcript-body"


class TranscriptRole(StrEnum):
    """Presentation classification of one transcript entry."""

    USER = "user"
    ASSISTANT = "assistant"
    CLARIFY = "clarify"
    ERROR = "error"
    HINT = "hint"


@dataclass(frozen=True, slots=True)
class TranscriptEntry:
    """One accepted transcript turn (presentation only)."""

    role: TranscriptRole
    text: str


_PREFIX: dict[TranscriptRole, str] = {
    TranscriptRole.USER: "Вы: ",
    TranscriptRole.ASSISTANT: "Ассистент: ",
    TranscriptRole.CLARIFY: "Уточнение: ",
    TranscriptRole.ERROR: "",
    TranscriptRole.HINT: "Примечание: ",
}

_PREFIX_STYLE: dict[TranscriptRole, str] = {
    TranscriptRole.USER: "bold cyan",
    TranscriptRole.ASSISTANT: "bold green",
    TranscriptRole.CLARIFY: "bold yellow",
    TranscriptRole.HINT: "dim",
}

_TEXT_STYLE: dict[TranscriptRole, str] = {
    TranscriptRole.ERROR: "red",
    TranscriptRole.HINT: "dim",
}


def _render_entries(entries: tuple[TranscriptEntry, ...]) -> Text:
    """Build plain Rich ``Text`` from entries; never parses model markup."""
    rendered = Text()
    for index, entry in enumerate(entries):
        if index:
            rendered.append("\n\n")
        prefix = _PREFIX[entry.role]
        if prefix:
            rendered.append(prefix, style=_PREFIX_STYLE[entry.role])
        rendered.append(entry.text, style=_TEXT_STYLE.get(entry.role))
    return rendered


class TranscriptView(VerticalScroll):
    """Scrollable, append-only assistant transcript surface."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._entries: list[TranscriptEntry] = []

    def compose(self) -> ComposeResult:
        yield Static("", id=_BODY_ID)

    @property
    def entries(self) -> tuple[TranscriptEntry, ...]:
        """The accepted transcript entries, in order."""
        return tuple(self._entries)

    def append(self, role: TranscriptRole, text: str) -> None:
        """Append one accepted entry and scroll to the newest turn."""
        self._entries.append(TranscriptEntry(role, text))
        self._rebuild_body()

    def clear(self) -> None:
        """Drop all ephemeral entries (used only by tests/reset)."""
        self._entries.clear()
        self._rebuild_body()

    def _rebuild_body(self) -> None:
        self.query_one(f"#{_BODY_ID}", Static).update(_render_entries(tuple(self._entries)))
        self.call_after_refresh(self.scroll_end, animate=False)
