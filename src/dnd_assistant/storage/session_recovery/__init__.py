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

import importlib as _importlib

from dnd_assistant.storage.session_recovery.repository import (
    ObsidianSessionRecoveryRepository,
)
from dnd_assistant.storage.session_recovery.types import (
    RecoveryActionResult,
    RecoveryIssue,
    SessionRecoveryReport,
)


# Lazy import to avoid circular-import identity issues when storage.__init__
# is being loaded.  The canonical SessionRecoveryRepository protocol lives in
# storage.types; we re-export it here so that
#   from dnd_assistant.storage.session_recovery import SessionRecoveryRepository
# works identically to
#   from dnd_assistant.storage.types import SessionRecoveryRepository
def __getattr__(name: str):
    if name == "SessionRecoveryRepository":
        mod = _importlib.import_module("dnd_assistant.storage.types")
        return mod.SessionRecoveryRepository
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__: list[str] = [
    "ObsidianSessionRecoveryRepository",
    "RecoveryActionResult",
    "RecoveryIssue",
    "SessionRecoveryReport",
    "SessionRecoveryRepository",
]
