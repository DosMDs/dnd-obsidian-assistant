"""Cross-capability in-flight safety gate (TUI-04).

The assistant composition captures the active session mode/session identity at
composition time, and Campaign-State rebuild has no publication lock.  A
long-lived UI can therefore interleave an assistant run with a session mutation
or a Campaign-State rebuild.  This narrow gate serializes exactly those
exclusive operations at the **presentation** level:

- assistant submission;
- session start / note / end;
- Campaign-State rebuild.

It is deliberately tiny: one owner token, no queue, no retry, no scheduler, no
cancellation.  Read-only refresh/inspection bypasses the gate.

This gate is presentation protection only.  It is never the trusted
data-consistency/authorization boundary; repository/application revision and
conflict checks remain authoritative.
"""

from __future__ import annotations

from typing import Final

__all__ = [
    "EXCLUSIVE_ASSISTANT",
    "EXCLUSIVE_CAMPAIGN_STATE",
    "EXCLUSIVE_SESSION",
    "InFlightGate",
]

EXCLUSIVE_ASSISTANT: Final[str] = "assistant"
EXCLUSIVE_SESSION: Final[str] = "session"
EXCLUSIVE_CAMPAIGN_STATE: Final[str] = "campaign-state"


class InFlightGate:
    """Single-owner presentation-level exclusivity gate.

    The gate is mutated only from the Textual event loop (before a worker is
    started and from worker state callbacks), so it needs no internal locking.
    """

    def __init__(self) -> None:
        self._owner: str | None = None

    @property
    def owner(self) -> str | None:
        """The current exclusive owner, or ``None`` when idle."""
        return self._owner

    @property
    def is_busy(self) -> bool:
        """Whether any exclusive operation is currently in flight."""
        return self._owner is not None

    def acquire(self, owner: str) -> bool:
        """Claim exclusivity for ``owner`` iff the gate is idle."""
        if self._owner is not None:
            return False
        if not owner:
            raise ValueError("in-flight owner must be a non-empty string")
        self._owner = owner
        return True

    def release(self, owner: str) -> None:
        """Release the gate iff ``owner`` currently holds it."""
        if self._owner == owner:
            self._owner = None
