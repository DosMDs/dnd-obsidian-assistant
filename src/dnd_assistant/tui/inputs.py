"""Hardened single-line inputs for the TUI (TUI-05).

Pinned Textual ``Input._on_paste`` silently keeps only the first pasted line
(``event.text.splitlines()[0]``) and stops the event.  For canonical-facing
single-line fields that means silent user-data loss, which is never acceptable
without an explicit trusted contract.

These widgets intercept the public ``Paste`` event surface, call
``event.prevent_default()`` and ``event.stop()`` so the inherited ``Input``
behavior cannot run, and then apply the explicit accepted policy:

- :class:`SingleLineInput` rejects multiline paste with a Russian warning and
  leaves the existing value unchanged (zero mutation);
- :class:`TouchedEntitiesInput` normalizes line breaks to spaces so a pasted
  whitespace-separated literal ID list keeps its literal-ID semantics and order
  (no entity inference).

Accepted text is inserted through the public ``Input`` editing API
(``insert_text_at_cursor`` / ``replace``); the private ``_on_paste`` hook is not
used.
"""

from __future__ import annotations

from typing import ClassVar

from textual import events
from textual.widgets import Input

__all__ = ["SingleLineInput", "TouchedEntitiesInput"]


class SingleLineInput(Input):
    """``Input`` that refuses multiline paste instead of silently truncating."""

    REJECT_MULTILINE_PASTE: ClassVar[bool] = True
    """Whether multiline paste must be rejected rather than normalized."""

    MULTILINE_PASTE_MESSAGE: ClassVar[str] = "Вставленный текст должен быть одной строкой."

    def on_paste(self, event: events.Paste) -> None:
        """Handle paste explicitly; never fall through to the base truncation."""
        event.prevent_default()
        event.stop()
        text = event.text
        if not text:
            return
        if "\n" in text or "\r" in text:
            if self.REJECT_MULTILINE_PASTE:
                self.notify(self.MULTILINE_PASTE_MESSAGE, severity="warning")
                return
            text = text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
        self._insert_pasted_text(text)

    def _insert_pasted_text(self, text: str) -> None:
        """Insert accepted paste text through the public ``Input`` API."""
        selection = self.selection
        if selection.is_empty:
            self.insert_text_at_cursor(text)
        else:
            self.replace(text, *selection)


class TouchedEntitiesInput(SingleLineInput):
    """Touched-ID input: multiline/whitespace paste maps to literal ID tokens."""

    REJECT_MULTILINE_PASTE = False
