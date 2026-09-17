"""Shared presentation-neutral AuditContext factory (TUI-04).

This module is the single UI-agnostic home for the audit identity used by
deterministic session mutations performed from a presentation surface (Typer
CLI and Textual TUI).  It owns no audit policy: it only stamps a fresh
operation id, the current UTC time and the caller-supplied ``source``.

Provenance stays explicit: the CLI composes with ``source="cli"`` and the TUI
with ``source="tui"``.  Extracting this seam keeps the CLI behaviour identical
while removing duplicated timestamp/operation-id construction.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from dnd_assistant.storage.audit import AuditContext

__all__ = [
    "build_audit_context",
    "new_operation_id",
    "now_utc",
]


def now_utc() -> datetime:
    """Return the current UTC time with timezone awareness."""
    return datetime.now(UTC)


def new_operation_id(prefix: str) -> str:
    """Return a unique operation ID with a readable prefix."""
    return f"{prefix}-{uuid4().hex}"


def build_audit_context(*, source: str, prefix: str) -> AuditContext:
    """Build a fresh presentation-neutral ``AuditContext``.

    Args:
        source: The audit source value (e.g. ``"cli"`` or ``"tui"``).
        prefix: The operation-ID prefix (e.g. ``"tui-session-start"``).

    Returns:
        A new ``AuditContext`` with current time, a unique operation ID and no
        model/prompt metadata.
    """
    return AuditContext(
        operation_id=new_operation_id(prefix),
        real_time=now_utc(),
        source=source,
        model_profile=None,
        prompt_version=None,
    )
