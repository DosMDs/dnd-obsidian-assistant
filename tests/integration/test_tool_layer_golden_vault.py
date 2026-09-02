"""Golden Vault integration tests for the complete MVP Tool Layer stack.

Tests the real concrete stack against a temporary copy of the Golden Vault
fixture.

Every mutation test operates on a ``tmp_path`` copy of the committed
fixture at ``tests/fixtures/golden_test_vault/``.  The committed fixture
is never used as a writable target.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from dnd_assistant.application.session_recovery import SessionRecoveryService
from dnd_assistant.application.session_runtime import SessionRuntimeService
from dnd_assistant.domain.calendar import (
    CalendarDefinition,
    CalendarMonth,
    DeterministicCalendarService,
    GameDate,
)
from dnd_assistant.domain.types import Visibility
from dnd_assistant.errors import NotFoundError
from dnd_assistant.retrieval.search import VaultSearchService
from dnd_assistant.storage.audit import AuditContext, AuditService
from dnd_assistant.storage.session_events import (
    ObsidianSessionEventRepository,
)
from dnd_assistant.storage.session_metadata import (
    ObsidianSessionMetadataRepository,
)
from dnd_assistant.storage.session_recovery import (
    ObsidianSessionRecoveryRepository,
)
from dnd_assistant.storage.vault_repository import (
    ObsidianVaultRepository,
)
from dnd_assistant.storage.world_time import (
    ObsidianWorldTimeRepository,
)
from dnd_assistant.tools.catalog import build_tool_registry_schema
from dnd_assistant.tools.executor import ToolExecutor
from dnd_assistant.tools.mvp_registry import build_mvp_tool_registry
from dnd_assistant.tools.types import (
    ExecutionContext,
    Permission,
    SessionMode,
)

# -- Fixture source path ----------------------------------------------------------

_GOLDEN_SOURCE = Path(__file__).resolve().parent.parent / "fixtures" / "golden_test_vault"

# -- Audit helper -----------------------------------------------------------------


def make_audit_context(
    operation_id: str = "test-001",
    source: str = "test",
    session: str | None = None,
) -> AuditContext:
    """Create an AuditContext for testing."""
    return AuditContext(
        operation_id=operation_id,
        real_time=datetime(2026, 8, 31, 18, 0, 0, tzinfo=UTC),
        source=source,
        session=session,
    )


# -- Temp-copy strategy -----------------------------------------------------------


def _copy_golden(tmp_path: Path) -> Path:
    """Create a writable temporary copy of the Golden Vault fixture."""
    dest = tmp_path / "Golden Vault Копия"
    assert " " in dest.name
    assert any(ord(ch) > 127 for ch in dest.name)
    shutil.copytree(_GOLDEN_SOURCE, dest)
    return dest


def golden_source_snapshot() -> dict[str, str]:
    """Return {relative_path: sha256} for every file under the Golden source."""
    snapshot: dict[str, str] = {}
    for path in sorted(_GOLDEN_SOURCE.rglob("*")):
        if path.is_file():
            rel = path.relative_to(_GOLDEN_SOURCE).as_posix()
            data = path.read_bytes()
            snapshot[rel] = hashlib.sha256(data).hexdigest()
    return snapshot


# -- Calendar definition ----------------------------------------------------------


def _make_calendar_definition() -> CalendarDefinition:
    """Create a compact deterministic calendar definition."""
    months = tuple(CalendarMonth(name=f"Month_{i}", days=30) for i in range(1, 13))
    return CalendarDefinition(
        calendar_id="golden_test_calendar",
        epoch=GameDate(year=1000, month="Month_1", day=1, hour=0, minute=0),
        months=months,
        hours_per_day=24,
        minutes_per_hour=60,
    )


# -- Full dependency stack builder ------------------------------------------------


def build_full_stack(vault_root: Path) -> dict[str, Any]:
    """Build the complete real dependency stack for Tool Layer testing."""
    audit_svc = AuditService(str(vault_root / "_system" / "audit" / "audit.jsonl"))

    repo = ObsidianVaultRepository(vault_root, audit_svc)
    search_svc = VaultSearchService(repository=repo)

    wt_repo = ObsidianWorldTimeRepository(vault_root, audit_svc)
    meta_repo = ObsidianSessionMetadataRepository(vault_root, audit_svc)
    event_repo = ObsidianSessionEventRepository(vault_root, audit_svc)

    runtime_svc = SessionRuntimeService(meta_repo, wt_repo, event_repo)
    recovery_repo = ObsidianSessionRecoveryRepository(vault_root, audit_svc)
    recovery_svc = SessionRecoveryService(recovery_repo)

    calendar_def = _make_calendar_definition()
    calendar_svc = DeterministicCalendarService(calendar_def)

    registry = build_mvp_tool_registry(
        search_service=search_svc,
        repository=repo,
        runtime_service=runtime_svc,
        recovery_service=recovery_svc,
        session_repository=meta_repo,
        event_repository=event_repo,
        world_time_repository=wt_repo,
        calendar_service=calendar_svc,
    )

    executor = ToolExecutor(registry)

    return {
        "audit_svc": audit_svc,
        "repo": repo,
        "search_svc": search_svc,
        "wt_repo": wt_repo,
        "meta_repo": meta_repo,
        "event_repo": event_repo,
        "runtime_svc": runtime_svc,
        "recovery_svc": recovery_svc,
        "calendar_svc": calendar_svc,
        "registry": registry,
        "executor": executor,
    }


# -- Pytest fixtures --------------------------------------------------------------


@pytest.fixture
def golden_copy(tmp_path: Path) -> Path:
    """Provide a writable temporary copy of the Golden Vault."""
    return _copy_golden(tmp_path)


@pytest.fixture
def source_snapshot() -> dict[str, str]:
    """Provide a byte-level snapshot of the committed Golden source."""
    return golden_source_snapshot()


@pytest.fixture
def stack(golden_copy: Path) -> dict[str, Any]:
    """Provide the full real dependency stack over the Golden copy."""
    return build_full_stack(golden_copy)


# ===== Source immutability proof ================================================


class TestGoldenSourceImmutability:
    """Prove the committed Golden fixture is never mutated by tests."""

    def test_source_unchanged_after_tool_lifecycle(
        self, golden_copy: Path, source_snapshot: dict[str, str]
    ) -> None:
        """Run a full Tool Layer lifecycle on the copy, then verify source bytes."""
        stack = build_full_stack(golden_copy)
        executor: ToolExecutor = stack["executor"]
        registry = stack["registry"]

        # Build catalog (must not mutate)
        _ = build_tool_registry_schema(registry)

        # Entity read
        executor.execute(
            "get_entity",
            input_data={"entity_id": "npc_varos"},
            context=ExecutionContext(
                granted_permission=Permission.READ,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
            ),
        )

        after = golden_source_snapshot()
        assert after == source_snapshot, "Golden source fixture was modified by test lifecycle"

    def test_no_generated_artifacts_in_source(self, source_snapshot: dict[str, str]) -> None:
        """Verify no derived/generated artifacts exist in the committed source."""
        assert "_system/world_time.json" in source_snapshot
        assert "_system/audit/audit.jsonl" in source_snapshot
        sqlite_files = [k for k in source_snapshot if ".sqlite" in k or ".db" in k]
        temp_files = [k for k in source_snapshot if ".tmp" in k or "~" in k]
        assert not sqlite_files, f"Unexpected SQLite files in source: {sqlite_files}"
        assert not temp_files, f"Unexpected temp files in source: {temp_files}"


# ===== Golden baseline assertions ===============================================


class TestGoldenBaseline:
    """Prove the Golden Vault baseline state is as expected."""

    def test_world_time_baseline(self, stack: dict[str, Any]) -> None:
        wt_repo: ObsidianWorldTimeRepository = stack["wt_repo"]
        wt = wt_repo.get_current_world_time()
        assert wt.current_world_tick == 13800
        assert wt.revision == 1

    def test_no_active_session(self, stack: dict[str, Any]) -> None:
        runtime_svc: SessionRuntimeService = stack["runtime_svc"]
        session = runtime_svc.get_active_session()
        assert session is None

    def test_completed_sessions_exist(self, stack: dict[str, Any]) -> None:
        meta_repo: ObsidianSessionMetadataRepository = stack["meta_repo"]
        all_meta = meta_repo.list_session_metadata()
        session_ids = {m.session.id for m in all_meta}
        for sid in ("S001", "S002", "S003", "S004", "S005"):
            assert sid in session_ids, f"Expected session {sid} in Golden Vault"

    def test_next_session_id_is_S006(self, stack: dict[str, Any]) -> None:
        meta_repo: ObsidianSessionMetadataRepository = stack["meta_repo"]
        next_id = meta_repo.allocate_next_session_id()
        assert next_id == "S006"

    def test_npc_varos_baseline(self, stack: dict[str, Any]) -> None:
        search_svc: VaultSearchService = stack["search_svc"]
        hit = search_svc.get_by_id("npc_varos")
        assert hit is not None
        assert hit.entity_id == "npc_varos"

        repo: ObsidianVaultRepository = stack["repo"]
        doc = repo.get_entity("npc_varos")
        assert doc.entity.id == "npc_varos"
        assert doc.entity.name == "Магистр Варос"
        assert doc.entity.visibility == Visibility.PLAYER
        assert doc.entity.revision == 4
        assert doc.body is not None and len(doc.body) > 0


# ===== Registry/catalog composition =============================================


class TestGoldenRegistryCatalog:
    """Prove the real composed registry and catalog are correct."""

    def test_registry_18_tools(self, stack: dict[str, Any]) -> None:
        registry = stack["registry"]
        assert len(registry) == 18

    def test_catalog_18_tools(self, stack: dict[str, Any]) -> None:
        registry = stack["registry"]
        schema = build_tool_registry_schema(registry)
        assert len(schema.tools) == 18

    def test_registry_names_match_catalog_names(self, stack: dict[str, Any]) -> None:
        registry = stack["registry"]
        schema = build_tool_registry_schema(registry)
        registry_names = [d.name for d in registry.list_definitions()]
        catalog_names = [t.name for t in schema.tools]
        assert registry_names == catalog_names

    def test_catalog_json_serializable(self, stack: dict[str, Any]) -> None:
        registry = stack["registry"]
        schema = build_tool_registry_schema(registry)
        payload = schema.model_dump(mode="json")
        serialized = json.dumps(payload, sort_keys=True)
        parsed = json.loads(serialized)
        assert len(parsed["tools"]) == 18

    def test_catalog_no_provider_keys(self, stack: dict[str, Any]) -> None:
        registry = stack["registry"]
        schema = build_tool_registry_schema(registry)
        payload = schema.model_dump(mode="json")
        for tool in payload["tools"]:
            assert "type" not in tool or tool.get("type") == "object"
            assert "function" not in tool
            assert "parameters" not in tool.get("input_schema", {})

    def test_catalog_causes_zero_vault_mutation(self, stack: dict[str, Any]) -> None:
        registry = stack["registry"]
        wt_repo: ObsidianWorldTimeRepository = stack["wt_repo"]
        before_wt = wt_repo.get_current_world_time()
        _ = build_tool_registry_schema(registry)
        after_wt = wt_repo.get_current_world_time()
        assert after_wt.current_world_tick == before_wt.current_world_tick
        assert after_wt.revision == before_wt.revision


# ===== Entity-read path =========================================================


class TestGoldenEntityRead:
    """Prove entity read tools work through the full composed stack."""

    def test_get_entity_varos(self, stack: dict[str, Any]) -> None:
        executor: ToolExecutor = stack["executor"]
        result = executor.execute(
            "get_entity",
            input_data={"entity_id": "npc_varos"},
            context=ExecutionContext(
                granted_permission=Permission.READ,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
            ),
        )
        assert result.entity.id == "npc_varos"
        assert result.entity.visibility == Visibility.PLAYER
        assert result.entity.revision == 4
        assert result.body is not None and len(result.body) > 0


# ===== Entity-mutation path =====================================================


class TestGoldenEntityMutation:
    """Prove entity mutation tools work through the full composed stack.

    All mutations operate on the temporary copy only.
    """

    def test_patch_entity_varos(self, stack: dict[str, Any]) -> None:
        executor: ToolExecutor = stack["executor"]
        result = executor.execute(
            "patch_entity",
            input_data={
                "entity_id": "npc_varos",
                "expected_revision": 4,
                "patch": {"name": "Магистр Варос Обновлённый"},
            },
            context=ExecutionContext(
                granted_permission=Permission.WRITE,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
                audit=make_audit_context(operation_id="patch-varos-s707"),
            ),
        )
        assert result.entity.id == "npc_varos"
        assert result.entity.revision == 5
        assert result.entity.name == "Магистр Варос Обновлённый"
        assert result.body is not None

    def test_patch_preserves_body(self, stack: dict[str, Any]) -> None:
        """Patch must not change the Markdown body."""
        executor: ToolExecutor = stack["executor"]
        # Read first
        read_result = executor.execute(
            "get_entity",
            input_data={"entity_id": "npc_varos"},
            context=ExecutionContext(
                granted_permission=Permission.READ,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
            ),
        )
        original_body = read_result.body

        executor.execute(
            "patch_entity",
            input_data={
                "entity_id": "npc_varos",
                "expected_revision": 4,
                "patch": {"name": "Магистр Варос Обновлённый"},
            },
            context=ExecutionContext(
                granted_permission=Permission.WRITE,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
                audit=make_audit_context(operation_id="patch-body-check"),
            ),
        )
        # Re-read
        read_again = executor.execute(
            "get_entity",
            input_data={"entity_id": "npc_varos"},
            context=ExecutionContext(
                granted_permission=Permission.READ,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
            ),
        )
        assert read_again.body == original_body

    def test_patch_preserves_extra_frontmatter(self, stack: dict[str, Any]) -> None:
        """Patch must preserve unknown/extra frontmatter such as aliases/source."""
        executor: ToolExecutor = stack["executor"]
        repo: ObsidianVaultRepository = stack["repo"]

        executor.execute(
            "patch_entity",
            input_data={
                "entity_id": "npc_varos",
                "expected_revision": 4,
                "patch": {"name": "Магистр Варос Обновлённый"},
            },
            context=ExecutionContext(
                granted_permission=Permission.WRITE,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
                audit=make_audit_context(operation_id="patch-extra-check"),
            ),
        )
        # Read raw document from repository
        doc = repo.get_entity("npc_varos")
        # Extra frontmatter should be preserved (aliases, source_type, source_ref, etc.)
        assert doc.extra_frontmatter is not None
        assert "aliases" in doc.extra_frontmatter
        assert "source_type" in doc.extra_frontmatter

    def test_append_entity_fact(self, stack: dict[str, Any]) -> None:
        executor: ToolExecutor = stack["executor"]
        # Golden baseline has revision 4 for npc_varos
        result = executor.execute(
            "append_entity_fact",
            input_data={
                "entity_id": "npc_varos",
                "expected_revision": 4,
                "fact": "Недавно обновил свои полномочия",
            },
            context=ExecutionContext(
                granted_permission=Permission.WRITE,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
                audit=make_audit_context(operation_id="append-fact-s707"),
            ),
        )
        assert result.entity.id == "npc_varos"
        assert result.entity.revision == 5
        assert result.body is not None

    def test_append_preserves_original_body_prefix(self, stack: dict[str, Any]) -> None:
        """Original body must remain a prefix of the new body after append."""
        executor: ToolExecutor = stack["executor"]
        # Read first
        read_result = executor.execute(
            "get_entity",
            input_data={"entity_id": "npc_varos"},
            context=ExecutionContext(
                granted_permission=Permission.READ,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
            ),
        )
        original_body = read_result.body

        executor.execute(
            "append_entity_fact",
            input_data={
                "entity_id": "npc_varos",
                "expected_revision": 4,
                "fact": "Новый факт",
            },
            context=ExecutionContext(
                granted_permission=Permission.WRITE,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
                audit=make_audit_context(operation_id="append-prefix-check"),
            ),
        )
        read_again = executor.execute(
            "get_entity",
            input_data={"entity_id": "npc_varos"},
            context=ExecutionContext(
                granted_permission=Permission.READ,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
            ),
        )
        assert read_again.body.startswith(original_body)

    def test_entity_state_survives_reconstruction(self, stack: dict[str, Any]) -> None:
        """Reconstruct the repository and verify state survives."""
        executor: ToolExecutor = stack["executor"]
        vault_root = stack["repo"]._vault_root  # type: ignore[attr-defined]

        executor.execute(
            "patch_entity",
            input_data={
                "entity_id": "npc_varos",
                "expected_revision": 4,
                "patch": {"name": "Магистр Варос Обновлённый"},
            },
            context=ExecutionContext(
                granted_permission=Permission.WRITE,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
                audit=make_audit_context(operation_id="patch-survive-check"),
            ),
        )

        # Reconstruct
        new_audit = AuditService(str(vault_root / "_system" / "audit" / "audit.jsonl"))
        new_repo = ObsidianVaultRepository(vault_root, new_audit)
        doc = new_repo.get_entity("npc_varos")
        assert doc.entity.revision == 5
        assert doc.entity.name == "Магистр Варос Обновлённый"


# ===== Hidden-entity safety =====================================================


class TestGoldenHiddenEntity:
    """Prove hidden (DM) entities are protected through the composed stack."""

    def test_get_hidden_entity_fails(self, stack: dict[str, Any]) -> None:
        executor: ToolExecutor = stack["executor"]
        with pytest.raises(NotFoundError):
            executor.execute(
                "get_entity",
                input_data={"entity_id": "npc_archivist_kell"},
                context=ExecutionContext(
                    granted_permission=Permission.READ,
                    session_mode=SessionMode.NO_ACTIVE_SESSION,
                ),
            )

    def test_patch_hidden_entity_fails(self, stack: dict[str, Any]) -> None:
        executor: ToolExecutor = stack["executor"]
        with pytest.raises(NotFoundError):
            executor.execute(
                "patch_entity",
                input_data={
                    "entity_id": "npc_archivist_kell",
                    "expected_revision": 1,
                    "patch": {"name": "Hacked"},
                },
                context=ExecutionContext(
                    granted_permission=Permission.WRITE,
                    session_mode=SessionMode.NO_ACTIVE_SESSION,
                    audit=make_audit_context(operation_id="hidden-patch-attempt"),
                ),
            )


# ===== World-time path ==========================================================


class TestGoldenWorldTime:
    """Prove world-time tools work through the full composed stack."""

    def test_get_world_time(self, stack: dict[str, Any]) -> None:
        executor: ToolExecutor = stack["executor"]
        result = executor.execute(
            "get_world_time",
            input_data={},
            context=ExecutionContext(
                granted_permission=Permission.READ,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
            ),
        )
        assert result.world_time.current_world_tick == 13800
        assert result.world_time.revision == 1

    def test_advance_world_time(self, stack: dict[str, Any]) -> None:
        executor: ToolExecutor = stack["executor"]
        result = executor.execute(
            "advance_world_time",
            input_data={
                "minutes": 120,
                "expected_revision": 1,
            },
            context=ExecutionContext(
                granted_permission=Permission.WRITE,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
                audit=make_audit_context(operation_id="advance-wt-s707"),
            ),
        )
        assert result.world_time.current_world_tick == 13920
        assert result.world_time.revision == 2

    def test_get_world_time_after_advance(self, stack: dict[str, Any]) -> None:
        """Verify get_world_time returns authoritative persisted state after advance."""
        executor: ToolExecutor = stack["executor"]
        executor.execute(
            "advance_world_time",
            input_data={
                "minutes": 120,
                "expected_revision": 1,
            },
            context=ExecutionContext(
                granted_permission=Permission.WRITE,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
                audit=make_audit_context(operation_id="advance-wt-before-get"),
            ),
        )
        result = executor.execute(
            "get_world_time",
            input_data={},
            context=ExecutionContext(
                granted_permission=Permission.READ,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
            ),
        )
        assert result.world_time.current_world_tick == 13920
        assert result.world_time.revision == 2

    def test_world_time_survives_reconstruction(self, stack: dict[str, Any]) -> None:
        """Reconstruct WorldTimeRepository and verify state survives."""
        executor: ToolExecutor = stack["executor"]
        vault_root = stack["repo"]._vault_root  # type: ignore[attr-defined]

        executor.execute(
            "advance_world_time",
            input_data={
                "minutes": 120,
                "expected_revision": 1,
            },
            context=ExecutionContext(
                granted_permission=Permission.WRITE,
                session_mode=SessionMode.NO_ACTIVE_SESSION,
                audit=make_audit_context(operation_id="advance-wt-reconstruct"),
            ),
        )

        new_audit = AuditService(str(vault_root / "_system" / "audit" / "audit.jsonl"))
        new_wt_repo = ObsidianWorldTimeRepository(vault_root, new_audit)
        wt = new_wt_repo.get_current_world_time()
        assert wt.current_world_tick == 13920
        assert wt.revision == 2


# ===== Session path =============================================================
