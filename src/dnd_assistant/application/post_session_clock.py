"""S11-06 injectable real-time source for post-session processing.

Ledger events require timezone-aware real timestamps.  Production uses the
system UTC clock; canonical tests inject a fixed clock so they never depend on
uncontrolled wall-clock time.  Real timestamps are provenance only: they never
participate in the prepared-input fingerprint, the ChangeSet fingerprint,
``EntityId`` allocation or artifact semantic content.

This module belongs to the application layer and must not import from:
    storage, models, ollama, pydantic_ai, tools, cli, retrieval
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime

PostSessionClock = Callable[[], datetime]
"""A trusted source of timezone-aware real time."""


def system_utc_now() -> datetime:
    """Return the current timezone-aware UTC time."""
    return datetime.now(UTC)


__all__ = ["PostSessionClock", "system_utc_now"]
