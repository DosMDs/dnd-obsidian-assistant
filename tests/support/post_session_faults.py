"""S11-08 test-only fault-injection helpers for the post-session processor.

These wrappers deliberately live under ``tests/support`` and add **no**
production surface.  They delegate every unmodified call to the real store via
``__getattr__`` and override only the operation under test, so a wrapped store
still satisfies the corresponding ``runtime_checkable`` protocol.

``AbruptProcessCrash`` derives directly from ``BaseException`` so it bypasses
the processor's ``except Exception`` failure recording and approximates a
process dying after a durable boundary.  It is used only where a caught typed
failure would be a materially different scenario.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from dnd_assistant.errors import StorageError

__all__ = [
    "AbruptProcessCrash",
    "FaultingArtifactStore",
    "FaultingChangeSetStore",
    "FaultingProcessingStore",
    "Predicate",
    "always",
]

Predicate = Callable[[str], bool]


def always(_content: str) -> bool:
    """Predicate that matches every call."""
    return True


class AbruptProcessCrash(BaseException):
    """Test-only abrupt interruption (bypasses ``except Exception``)."""


class _Delegating:
    """Forward every unmodified attribute access to the wrapped object."""

    _real: Any

    def __init__(self, real: Any) -> None:
        self._real = real

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)


class FaultingProcessingStore(_Delegating):
    """Processing-store wrapper injecting ledger append/read faults.

    ``fail_append_before``  -> raise before any bytes are written (definite).
    ``fail_append_after``   -> write the line, then raise (uncertain write).
    ``crash_append_after``  -> write the line, then raise ``AbruptProcessCrash``.
    ``fail_read``           -> raise on the next read (predicate-based).
    """

    def __init__(
        self,
        real: object,
        *,
        fail_append_before: Predicate | None = None,
        fail_append_after: Predicate | None = None,
        crash_append_after: Predicate | None = None,
        fail_read: Callable[[], bool] | None = None,
    ) -> None:
        super().__init__(real)
        self._fail_append_before = fail_append_before
        self._fail_append_after = fail_append_after
        self._crash_append_after = crash_append_after
        self._fail_read = fail_read

    def append_ledger_line(self, session_id: str, content: str) -> None:
        if self._fail_append_before is not None and self._fail_append_before(content):
            raise StorageError("injected append failure before write")
        if self._crash_append_after is not None and self._crash_append_after(content):
            self._real.append_ledger_line(session_id, content)
            raise AbruptProcessCrash("injected crash after append")
        if self._fail_append_after is not None and self._fail_append_after(content):
            self._real.append_ledger_line(session_id, content)
            raise StorageError("injected uncertain append failure after write")
        self._real.append_ledger_line(session_id, content)

    def read_ledger_if_present(self, session_id: str) -> str | None:
        if self._fail_read is not None and self._fail_read():
            raise StorageError("injected ledger read failure")
        return self._real.read_ledger_if_present(session_id)


class FaultingArtifactStore(_Delegating):
    """Artifact-store wrapper injecting claim/persist faults.

    ``fail_claim``          -> raise before the claim is attempted.
    ``fail_persist``        -> raise before the artifact is written.
    ``crash_persist_after`` -> write the artifact, then raise ``AbruptProcessCrash``.
    """

    def __init__(
        self,
        real: object,
        *,
        fail_claim: Predicate | None = None,
        fail_persist: Predicate | None = None,
        crash_persist_after: Predicate | None = None,
    ) -> None:
        super().__init__(real)
        self._fail_claim = fail_claim
        self._fail_persist = fail_persist
        self._crash_persist_after = crash_persist_after

    def claim_attempt(self, session_id: str, attempt_id: str) -> bool:
        if self._fail_claim is not None and self._fail_claim(attempt_id):
            raise StorageError("injected claim failure")
        return self._real.claim_attempt(session_id, attempt_id)

    def persist_artifact(
        self,
        session_id: str,
        attempt_id: str,
        artifact_kind: object,
        text: str,
    ) -> object:
        key = getattr(artifact_kind, "value", str(artifact_kind))
        if self._fail_persist is not None and self._fail_persist(key):
            raise StorageError("injected artifact persistence failure before write")
        result = self._real.persist_artifact(session_id, attempt_id, artifact_kind, text)
        if self._crash_persist_after is not None and self._crash_persist_after(key):
            raise AbruptProcessCrash("injected crash after artifact write")
        return result


class FaultingChangeSetStore(_Delegating):
    """ChangeSet-store wrapper injecting proposal faults.

    ``fail_create_proposal``  -> raise before the proposal is written.
    ``crash_create_after``    -> write the proposal, then raise ``AbruptProcessCrash``.
    ``fail_read_proposal``    -> raise on proposal reads (predicate-based).
    """

    def __init__(
        self,
        real: object,
        *,
        fail_create_proposal: Predicate | None = None,
        crash_create_after: Predicate | None = None,
        fail_read_proposal: Predicate | None = None,
    ) -> None:
        super().__init__(real)
        self._fail_create_proposal = fail_create_proposal
        self._crash_create_after = crash_create_after
        self._fail_read_proposal = fail_read_proposal

    def create_proposal(self, changeset_id: str, content: str) -> None:
        if self._fail_create_proposal is not None and self._fail_create_proposal(changeset_id):
            raise StorageError("injected proposal create failure before write")
        self._real.create_proposal(changeset_id, content)
        if self._crash_create_after is not None and self._crash_create_after(changeset_id):
            raise AbruptProcessCrash("injected crash after proposal write")

    def read_proposal_if_present(self, changeset_id: str) -> str | None:
        if self._fail_read_proposal is not None and self._fail_read_proposal(changeset_id):
            raise StorageError("injected proposal read failure")
        return self._real.read_proposal_if_present(changeset_id)
