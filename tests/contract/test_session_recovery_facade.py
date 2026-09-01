"""Contract tests: session recovery public facade.

Verifies that the public import surface of the session recovery package
is preserved after decomposition.
"""

from __future__ import annotations

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
