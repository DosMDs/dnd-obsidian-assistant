"""Session runtime recovery — inspection and explicit repair.

This package provides:

- ``RecoveryIssue`` — typed issue found during runtime inspection.
- ``SessionRecoveryReport`` — ordered collection of issues.
- ``RecoveryActionResult`` — result of a recovery operation.
- ``ObsidianSessionRecoveryRepository`` — concrete filesystem-backed
  implementation.

This package belongs to the storage layer and must not import from:
    models, retrieval, tools, application, cli, ollama
"""

import os as _os  # noqa: F401 — re-exported for backward compat monkeypatch targets

from dnd_assistant.storage.session_recovery.repository import (
    ObsidianSessionRecoveryRepository,
)
from dnd_assistant.storage.session_recovery.support import (
    _bytes_hash,  # noqa: F401 — re-exported for backward compat (C05 test)
    _read_exact_bytes,  # noqa: F401 — re-exported for backward compat
    _require_clean_audit_log,  # noqa: F401 — re-exported for backward compat
)
from dnd_assistant.storage.session_recovery.types import (
    RecoveryActionResult,
    RecoveryIssue,
    SessionRecoveryReport,
)

# Backward-compatible alias for old test monkeypatch targets
os = _os

__all__: list[str] = [
    "ObsidianSessionRecoveryRepository",
    "RecoveryActionResult",
    "RecoveryIssue",
    "SessionRecoveryReport",
]
