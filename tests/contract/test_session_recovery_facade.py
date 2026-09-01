"""Contract tests: session recovery public facade.

Verifies that the public import surface of the session recovery package
is preserved after decomposition.
"""

from __future__ import annotations

import inspect

from dnd_assistant.storage import (
    ObsidianSessionRecoveryRepository,
    RecoveryActionResult,
    RecoveryIssue,
    SessionRecoveryReport,
)
from dnd_assistant.storage.session_recovery import (
    ObsidianSessionRecoveryRepository as PkgObsidianSessionRecoveryRepository,
)
from dnd_assistant.storage.session_recovery import (
    RecoveryActionResult as PkgRecoveryActionResult,
)
from dnd_assistant.storage.session_recovery import (
    RecoveryIssue as PkgRecoveryIssue,
)
from dnd_assistant.storage.session_recovery import (
    SessionRecoveryReport as PkgSessionRecoveryReport,
)

# SessionRecoveryRepository is imported lazily inside test functions
# to avoid identity issues when boundary tests clean sys.modules.


class TestPublicFacadeImports:
    """Public imports from both storage facade and package root."""

    def test_storage_facade_imports(self) -> None:
        assert ObsidianSessionRecoveryRepository is PkgObsidianSessionRecoveryRepository
        assert RecoveryActionResult is PkgRecoveryActionResult
        assert RecoveryIssue is PkgRecoveryIssue
        assert SessionRecoveryReport is PkgSessionRecoveryReport

    def test_protocol_resolution(self) -> None:
        """SessionRecoveryRepository protocol is resolvable from storage.types."""
        from dnd_assistant.storage.types import SessionRecoveryRepository as ProtocolType

        # Verify the protocol has the expected methods
        for method in (
            "inspect_runtime",
            "repair_audit_tail",
            "cleanup_partial_start",
            "repair_event_tail",
        ):
            assert hasattr(ProtocolType, method), f"Protocol missing method {method}"

    def test_concrete_satisfies_protocol(self) -> None:
        """ObsidianSessionRecoveryRepository structurally satisfies the protocol."""

        protocol_methods = {
            "inspect_runtime",
            "repair_audit_tail",
            "cleanup_partial_start",
            "repair_event_tail",
        }
        for method in protocol_methods:
            assert hasattr(ObsidianSessionRecoveryRepository, method), (
                f"Missing method {method} on concrete repository"
            )

    def test_recovery_issue_constructable(self) -> None:
        issue = RecoveryIssue(code="test", session_id="S001", recoverable=True)
        assert issue.code == "test"
        assert issue.session_id == "S001"
        assert issue.recoverable is True

    def test_recovery_report_constructable(self) -> None:
        report = SessionRecoveryReport()
        assert not report.has_issues

    def test_recovery_action_result_constructable(self) -> None:
        result = RecoveryActionResult(operation="test", before_hash="a", after_hash="b")
        assert result.operation == "test"

    def test_session_recovery_repository_importable_from_package(self) -> None:
        """SessionRecoveryRepository is importable from session_recovery package root."""
        from dnd_assistant.storage.session_recovery import SessionRecoveryRepository

        assert SessionRecoveryRepository is not None

    def test_session_recovery_repository_is_canonical(self) -> None:
        """Package-root SessionRecoveryRepository is identical to storage.types."""
        from dnd_assistant.storage.session_recovery import SessionRecoveryRepository as Facade
        from dnd_assistant.storage.types import SessionRecoveryRepository as Canonical

        assert Facade is Canonical


class TestPublicConcreteSignatures:
    """Concrete public method signatures must retain typed audit parameters."""

    def test_repair_audit_tail_audit_typed(self) -> None:
        sig = inspect.signature(ObsidianSessionRecoveryRepository.repair_audit_tail)
        params = list(sig.parameters.values())
        audit_param = next(p for p in params if p.name == "audit")
        assert audit_param.annotation is not inspect.Parameter.empty
        assert "AuditContext" in str(audit_param.annotation)

    def test_cleanup_partial_start_audit_typed(self) -> None:
        sig = inspect.signature(ObsidianSessionRecoveryRepository.cleanup_partial_start)
        params = list(sig.parameters.values())
        audit_param = next(p for p in params if p.name == "audit")
        assert audit_param.annotation is not inspect.Parameter.empty
        assert "AuditContext" in str(audit_param.annotation)

    def test_repair_event_tail_audit_typed(self) -> None:
        sig = inspect.signature(ObsidianSessionRecoveryRepository.repair_event_tail)
        params = list(sig.parameters.values())
        audit_param = next(p for p in params if p.name == "audit")
        assert audit_param.annotation is not inspect.Parameter.empty
        assert "AuditContext" in str(audit_param.annotation)
