"""Golden Vault integration tests for session/cross-family Tool Layer paths.

Tests session lifecycle, cross-family audit, permission isolation, and
typed-result verification through the full composed Tool Layer stack.

This file is split from ``test_tool_layer_golden_vault.py`` to stay under
the 1000-line test-module hard limit.
"""

from __future__ import annotations

from typing import Any

import pytest

from dnd_assistant.errors import ConflictError
from dnd_assistant.storage.audit import AuditService
from dnd_assistant.storage.world_time import (
    ObsidianWorldTimeRepository,
)
from dnd_assistant.tools.executor import ToolExecutor
from dnd_assistant.tools.types import (
    ExecutionContext,
    Permission,
    SessionMode,
)

# ── Import shared helpers and fixtures from main module ──────────────────────

pytest_plugins = ["tests.integration.test_tool_layer_golden_vault"]

from tests.integration.test_tool_layer_golden_vault import (  # noqa: E402
    make_audit_context,
)

# ===== Session path =============================================================


class TestGoldenSession:
    """Prove session tools work through the full composed stack."""

    def test_start_session(self, stack: dict[str, Any]) -> None:
        executor: ToolExecutor = stack["executor"]
        result = executor.execute(
            "start_session",
            input_data={},
            context=ExecutionContext(
                granted_permission=Permission.WRITE,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
                audit=make_audit_context(operation_id="start-s006-s707"),
            ),
        )
        assert result.session.id == "S006"
        assert result.session.status == "active"
        assert result.session.world_tick_start == 13800

    def test_record_note(self, stack: dict[str, Any]) -> None:
        executor: ToolExecutor = stack["executor"]
        executor.execute(
            "start_session",
            input_data={},
            context=ExecutionContext(
                granted_permission=Permission.WRITE,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
                audit=make_audit_context(operation_id="start-for-note"),
            ),
        )
        result = executor.execute(
            "record_note",
            input_data={"text": "Тестовая заметка во время сессии"},
            context=ExecutionContext(
                granted_permission=Permission.WRITE,
                session_mode=SessionMode.ACTIVE_SESSION,
                audit=make_audit_context(operation_id="note-s006-s707", session="S006"),
            ),
        )
        assert result.event.type == "note"
        assert result.event.extra_fields["text"] == "Тестовая заметка во время сессии"

    def test_list_session_events(self, stack: dict[str, Any]) -> None:
        executor: ToolExecutor = stack["executor"]
        executor.execute(
            "start_session",
            input_data={},
            context=ExecutionContext(
                granted_permission=Permission.WRITE,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
                audit=make_audit_context(operation_id="start-for-events"),
            ),
        )
        executor.execute(
            "record_note",
            input_data={"text": "Заметка для проверки событий"},
            context=ExecutionContext(
                granted_permission=Permission.WRITE,
                session_mode=SessionMode.ACTIVE_SESSION,
                audit=make_audit_context(operation_id="note-for-events", session="S006"),
            ),
        )
        result = executor.execute(
            "list_session_events",
            input_data={"session_id": "S006"},
            context=ExecutionContext(
                granted_permission=Permission.READ,
                session_mode=SessionMode.ACTIVE_SESSION,
            ),
        )
        assert len(result.events) >= 1
        note_events = [e for e in result.events if e.type == "note"]
        assert len(note_events) >= 1

    def test_end_session(self, stack: dict[str, Any]) -> None:
        executor: ToolExecutor = stack["executor"]
        executor.execute(
            "start_session",
            input_data={},
            context=ExecutionContext(
                granted_permission=Permission.WRITE,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
                audit=make_audit_context(operation_id="start-for-end"),
            ),
        )
        result = executor.execute(
            "end_session",
            input_data={"touched_entity_ids": ["npc_varos"]},
            context=ExecutionContext(
                granted_permission=Permission.WRITE,
                session_mode=SessionMode.ACTIVE_SESSION,
                audit=make_audit_context(operation_id="end-s006-s707", session="S006"),
            ),
        )
        assert result.session.id == "S006"
        assert result.session.status == "completed"
        assert result.session.world_tick_end == 13800

    def test_get_session_after_end(self, stack: dict[str, Any]) -> None:
        executor: ToolExecutor = stack["executor"]
        executor.execute(
            "start_session",
            input_data={},
            context=ExecutionContext(
                granted_permission=Permission.WRITE,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
                audit=make_audit_context(operation_id="start-for-get"),
            ),
        )
        executor.execute(
            "end_session",
            input_data={"touched_entity_ids": ["npc_varos"]},
            context=ExecutionContext(
                granted_permission=Permission.WRITE,
                session_mode=SessionMode.ACTIVE_SESSION,
                audit=make_audit_context(operation_id="end-for-get", session="S006"),
            ),
        )
        result = executor.execute(
            "get_session",
            input_data={"session_id": "S006"},
            context=ExecutionContext(
                granted_permission=Permission.READ,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
            ),
        )
        assert result.session.id == "S006"
        assert result.session.status == "completed"
        assert result.session.world_tick_end == 13800

    def test_get_active_session_returns_none_after_end(self, stack: dict[str, Any]) -> None:
        executor: ToolExecutor = stack["executor"]
        executor.execute(
            "start_session",
            input_data={},
            context=ExecutionContext(
                granted_permission=Permission.WRITE,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
                audit=make_audit_context(operation_id="start-for-active"),
            ),
        )
        executor.execute(
            "end_session",
            input_data={},
            context=ExecutionContext(
                granted_permission=Permission.WRITE,
                session_mode=SessionMode.ACTIVE_SESSION,
                audit=make_audit_context(operation_id="end-for-active", session="S006"),
            ),
        )
        result = executor.execute(
            "get_active_session",
            input_data={},
            context=ExecutionContext(
                granted_permission=Permission.READ,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
            ),
        )
        assert result.session is None


# ===== Cross-family audit =======================================================


class TestGoldenCrossFamilyAudit:
    """Prove audit records are produced by underlying services, not the Tool Layer."""

    def test_entity_mutation_produces_audit(self, stack: dict[str, Any]) -> None:
        executor: ToolExecutor = stack["executor"]
        executor.execute(
            "patch_entity",
            input_data={
                "entity_id": "npc_varos",
                "expected_revision": 4,
                "patch": {"name": "Audit Check"},
            },
            context=ExecutionContext(
                granted_permission=Permission.WRITE,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
                audit=make_audit_context(operation_id="audit-entity-patch"),
            ),
        )
        audit_svc: AuditService = stack["audit_svc"]
        records = audit_svc.read_all()
        op_ids = [r.operation_id for r in records]
        assert "audit-entity-patch" in op_ids

    def test_world_time_mutation_produces_audit(self, stack: dict[str, Any]) -> None:
        executor: ToolExecutor = stack["executor"]
        executor.execute(
            "advance_world_time",
            input_data={
                "minutes": 60,
                "expected_revision": 1,
            },
            context=ExecutionContext(
                granted_permission=Permission.WRITE,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
                audit=make_audit_context(operation_id="audit-wt-advance"),
            ),
        )
        audit_svc: AuditService = stack["audit_svc"]
        records = audit_svc.read_all()
        op_ids = [r.operation_id for r in records]
        assert "audit-wt-advance" in op_ids

    def test_session_mutation_produces_audit(self, stack: dict[str, Any]) -> None:
        executor: ToolExecutor = stack["executor"]
        executor.execute(
            "start_session",
            input_data={},
            context=ExecutionContext(
                granted_permission=Permission.WRITE,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
                audit=make_audit_context(operation_id="audit-session-start"),
            ),
        )
        audit_svc: AuditService = stack["audit_svc"]
        records = audit_svc.read_all()
        op_ids = [r.operation_id for r in records]
        assert "audit-session-start" in op_ids


# ===== Permission isolation =====================================================


class TestGoldenPermissionIsolation:
    """Prove READ authority cannot call WRITE tools through the composed stack."""

    def test_read_cannot_start_session(self, stack: dict[str, Any]) -> None:
        executor: ToolExecutor = stack["executor"]
        with pytest.raises(ConflictError):
            executor.execute(
                "start_session",
                input_data={},
                context=ExecutionContext(
                    granted_permission=Permission.READ,
                    session_mode=SessionMode.NO_ACTIVE_SESSION,
                ),
            )

    def test_read_cannot_patch_entity(self, stack: dict[str, Any]) -> None:
        executor: ToolExecutor = stack["executor"]
        with pytest.raises(ConflictError):
            executor.execute(
                "patch_entity",
                input_data={
                    "entity_id": "npc_varos",
                    "expected_revision": 4,
                    "patch": {"name": "Should Not Work"},
                },
                context=ExecutionContext(
                    granted_permission=Permission.READ,
                    session_mode=SessionMode.NO_ACTIVE_SESSION,
                ),
            )

    def test_read_cannot_advance_world_time(self, stack: dict[str, Any]) -> None:
        executor: ToolExecutor = stack["executor"]
        with pytest.raises(ConflictError):
            executor.execute(
                "advance_world_time",
                input_data={
                    "minutes": 60,
                    "expected_revision": 1,
                },
                context=ExecutionContext(
                    granted_permission=Permission.READ,
                    session_mode=SessionMode.NO_ACTIVE_SESSION,
                ),
            )

    def test_no_mutation_on_permission_denied(self, stack: dict[str, Any]) -> None:
        wt_repo: ObsidianWorldTimeRepository = stack["wt_repo"]
        before = wt_repo.get_current_world_time()

        executor: ToolExecutor = stack["executor"]
        with pytest.raises(ConflictError):
            executor.execute(
                "advance_world_time",
                input_data={
                    "minutes": 60,
                    "expected_revision": 1,
                },
                context=ExecutionContext(
                    granted_permission=Permission.READ,
                    session_mode=SessionMode.NO_ACTIVE_SESSION,
                ),
            )

        after = wt_repo.get_current_world_time()
        assert after.current_world_tick == before.current_world_tick
        assert after.revision == before.revision


# ===== Typed-result isolation ===================================================


class TestGoldenTypedResult:
    """Prove ToolExecutor returns registered typed output models."""

    def test_get_entity_typed_output(self, stack: dict[str, Any]) -> None:
        registry = stack["registry"]
        executor: ToolExecutor = stack["executor"]
        defn = registry.get_definition("get_entity")
        result = executor.execute(
            "get_entity",
            input_data={"entity_id": "npc_varos"},
            context=ExecutionContext(
                granted_permission=Permission.READ,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
            ),
        )
        assert isinstance(result, defn.output_schema)

    def test_get_world_time_typed_output(self, stack: dict[str, Any]) -> None:
        registry = stack["registry"]
        executor: ToolExecutor = stack["executor"]
        defn = registry.get_definition("get_world_time")
        result = executor.execute(
            "get_world_time",
            input_data={},
            context=ExecutionContext(
                granted_permission=Permission.READ,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
            ),
        )
        assert isinstance(result, defn.output_schema)

    def test_start_session_typed_output(self, stack: dict[str, Any]) -> None:
        registry = stack["registry"]
        executor: ToolExecutor = stack["executor"]
        defn = registry.get_definition("start_session")
        result = executor.execute(
            "start_session",
            input_data={},
            context=ExecutionContext(
                granted_permission=Permission.WRITE,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
                audit=make_audit_context(operation_id="typed-start"),
            ),
        )
        assert isinstance(result, defn.output_schema)

    def test_search_entities_typed_output(self, stack: dict[str, Any]) -> None:
        registry = stack["registry"]
        executor: ToolExecutor = stack["executor"]
        defn = registry.get_definition("search_entities")
        result = executor.execute(
            "search_entities",
            input_data={"text": "Варос"},
            context=ExecutionContext(
                granted_permission=Permission.READ,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
            ),
        )
        assert isinstance(result, defn.output_schema)
