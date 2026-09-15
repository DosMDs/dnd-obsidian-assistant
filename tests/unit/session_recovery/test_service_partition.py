"""R1 tests: SessionRecoveryService partition narrows blocking, not detection.

``inspect_runtime`` must keep returning the complete raw report.  Only
``inspect_runtime_partition`` narrows blocking scope through an injected
ownership gate.
"""

from __future__ import annotations

from pathlib import Path

from dnd_assistant.application.session_recovery import (
    RecoveryPartition,
    SessionRecoveryService,
)
from dnd_assistant.storage.audit import AuditService
from dnd_assistant.storage.session_recovery import (
    ObsidianSessionRecoveryRepository,
    RecoveryIssue,
    SessionRecoveryReport,
)
from tests.unit.session_recovery.conftest import (
    make_audit_context,
    make_audit_record,
    start_session,
)


def _repo(vault_root: Path, audit_svc: AuditService) -> ObsidianSessionRecoveryRepository:
    return ObsidianSessionRecoveryRepository(vault_root, audit_svc)


class _FakeGate:
    """Delegates a single known operation id; everything else stays blocking."""

    def __init__(self, delegated_operation_id: str) -> None:
        self._delegated = delegated_operation_id

    def partition(self, report: SessionRecoveryReport) -> RecoveryPartition:
        delegated = tuple(i for i in report.issues if i.operation_id == self._delegated)
        blocking = tuple(i for i in report.issues if i.operation_id != self._delegated)
        return RecoveryPartition(blocking=blocking, externally_owned=delegated)


def _seed_intent(audit_svc: AuditService, operation_id: str, session: str = "S006") -> None:
    audit_svc.append(
        make_audit_record(
            make_audit_context(operation_id=operation_id, session=session),
            operation="create_entity",
            entity_id="npc-1",
            phase="intent",
        )
    )


def _unresolved(report: SessionRecoveryReport) -> list[RecoveryIssue]:
    return [i for i in report.issues if i.code == "unresolved_audit_intent"]


class TestServicePartition:
    def test_inspect_runtime_preserves_raw_issues(
        self, vault_root: Path, audit_svc: AuditService
    ) -> None:
        start_session(vault_root, "S006")
        _seed_intent(audit_svc, "cs-1:0")

        service = SessionRecoveryService(_repo(vault_root, audit_svc))
        report = service.inspect_runtime()

        assert [i.operation_id for i in _unresolved(report)] == ["cs-1:0"]

    def test_partition_without_gate_all_blocking(
        self, vault_root: Path, audit_svc: AuditService
    ) -> None:
        start_session(vault_root, "S006")
        _seed_intent(audit_svc, "cs-1:0")

        service = SessionRecoveryService(_repo(vault_root, audit_svc))
        partition = service.inspect_runtime_partition()

        assert partition.externally_owned == ()
        assert "unresolved_audit_intent" in {i.code for i in partition.blocking}

    def test_partition_delegates_gate_result_but_raw_is_unchanged(
        self, vault_root: Path, audit_svc: AuditService
    ) -> None:
        start_session(vault_root, "S006")
        _seed_intent(audit_svc, "cs-1:0")

        service = SessionRecoveryService(
            _repo(vault_root, audit_svc),
            ownership_gate=_FakeGate("cs-1:0"),
        )

        partition = service.inspect_runtime_partition()
        assert [i.operation_id for i in partition.externally_owned] == ["cs-1:0"]
        assert all(i.operation_id != "cs-1:0" for i in partition.blocking)

        # Raw detection/reporting scope is unchanged: the issue is still visible.
        assert [i.operation_id for i in _unresolved(service.inspect_runtime())] == ["cs-1:0"]

    def test_mixed_state_keeps_genuine_issue_blocking(
        self, vault_root: Path, audit_svc: AuditService
    ) -> None:
        start_session(vault_root, "S006")
        _seed_intent(audit_svc, "cs-1:0")
        _seed_intent(audit_svc, "genuine-op")

        service = SessionRecoveryService(
            _repo(vault_root, audit_svc),
            ownership_gate=_FakeGate("cs-1:0"),
        )
        partition = service.inspect_runtime_partition()

        assert [i.operation_id for i in partition.externally_owned] == ["cs-1:0"]
        assert {i.operation_id for i in partition.blocking} == {"genuine-op"}
