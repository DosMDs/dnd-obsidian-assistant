"""Integration tests for world-time mutation tools with real repository.

Covers:
- Real ObsidianWorldTimeRepository + ToolExecutor integration
- initialize -> read -> advance -> reconstructed repository read
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from dnd_assistant.domain.calendar import (
    CalendarDefinition,
    CalendarMonth,
    DeterministicCalendarService,
    GameDate,
    IntercalaryDay,
)
from dnd_assistant.storage.audit import AuditContext, AuditService
from dnd_assistant.storage.world_time import ObsidianWorldTimeRepository
from dnd_assistant.tools.executor import ToolExecutor
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import ExecutionContext, Permission, SessionMode
from dnd_assistant.tools.world_time_mutations import register_world_time_mutation_tools

_HARNER_CALENDAR = CalendarDefinition(
    calendar_id="harner",
    epoch=GameDate(year=0, month="Hammer", day=1),
    months=(CalendarMonth(name="Hammer", days=30), CalendarMonth(name="Alturiak", days=30)),
    intercalary_days=(IntercalaryDay(name="Midwinter", after_month="Hammer"),),
    hours_per_day=24,
    minutes_per_hour=60,
)


class TestRealRepositoryIntegration:
    """End-to-end sequence with real ObsidianWorldTimeRepository."""

    def test_initialize_advance_get_sequence(self, tmp_path: Path) -> None:
        vault_root = tmp_path / "vault"
        vault_root.mkdir()
        audit_dir = vault_root / "_system" / "audit"
        audit_dir.mkdir(parents=True)
        audit_service = AuditService(audit_dir / "audit.jsonl")
        repo = ObsidianWorldTimeRepository(vault_root, audit_service)
        calendar = DeterministicCalendarService(_HARNER_CALENDAR)

        reg = ToolRegistry()
        register_world_time_mutation_tools(
            reg, world_time_repository=repo, calendar_service=calendar
        )
        executor = ToolExecutor(reg)

        audit_ctx = AuditContext(
            operation_id="s7-05-e2e-001",
            real_time=datetime(2026, 9, 2, tzinfo=UTC),
            source="test",
        )
        ctx = ExecutionContext(
            granted_permission=Permission.WRITE,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
            audit=audit_ctx,
        )

        # 1. Initialize
        set_result = executor.execute(
            "set_world_time", input_data={"world_tick": 1000}, context=ctx
        )
        assert set_result.world_time.current_world_tick == 1000
        assert set_result.world_time.revision == 1

        # 2. Verify through direct repository read
        persisted = repo.get_current_world_time()
        assert persisted.current_world_tick == 1000
        assert persisted.revision == 1

        # 3. Advance
        advance_result = executor.execute(
            "advance_world_time", input_data={"minutes": 120, "expected_revision": 1}, context=ctx
        )
        assert advance_result.world_time.current_world_tick == 1120
        assert advance_result.world_time.revision == 2

        # 4. Verify state survives reconstruction
        repo2 = ObsidianWorldTimeRepository(vault_root, audit_service)
        persisted = repo2.get_current_world_time()
        assert persisted.current_world_tick == 1120
        assert persisted.revision == 2
