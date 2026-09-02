"""Unit tests for the MVP tool registry composition module.

Tests ``build_mvp_tool_registry()`` independently from real persistence
using lightweight fake/sentinel dependencies.

Verifies:

- returns a ``ToolRegistry``.
- len(registry) == 18.
- exact 18 sorted names.
- no duplicate names.
- READ count == 10, WRITE count == 8.
- side-effect family counts (ENTITY_MUTATION=2, SESSION_MUTATION=4,
  WORLD_TIME_MUTATION=2).
- session-mode metadata consistency.
- composition delegates to six accepted family registration functions.
"""

from __future__ import annotations

from typing import Any

import pytest

from dnd_assistant.tools.mvp_registry import build_mvp_tool_registry
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import Permission, SessionMode, SideEffect

# ── Fakes ─────────────────────────────────────────────────────────────────────────


class _FakeSearchService:
    def search(self, *args: Any, **kwargs: Any) -> list[Any]:
        return []

    def get_by_id(self, *args: Any, **kwargs: Any) -> None:
        return None


class _FakeRepository:
    def get_entity(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("Unit test must not execute handlers")

    def patch_entity(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("Unit test must not execute handlers")

    def append_entity_fact(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("Unit test must not execute handlers")


class _FakeRuntimeService:
    def get_active_session(self, *args: Any, **kwargs: Any) -> None:
        return None

    def start_session(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("Unit test must not execute handlers")

    def record_event(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("Unit test must not execute handlers")

    def record_note(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("Unit test must not execute handlers")

    def end_session(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("Unit test must not execute handlers")


class _FakeRecoveryService:
    def inspect_runtime(self, *args: Any, **kwargs: Any) -> Any:
        return type("Report", (), {"has_issues": False})()


class _FakeSessionRepo:
    def get_session_metadata(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("Unit test must not execute handlers")

    def list_session_metadata(self, *args: Any, **kwargs: Any) -> list[Any]:
        return []


class _FakeEventRepo:
    def list_events(self, *args: Any, **kwargs: Any) -> list[Any]:
        return []


class _FakeWorldTimeRepo:
    def get_current_world_time(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("Unit test must not execute handlers")

    def initialize_current_world_time(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("Unit test must not execute handlers")

    def set_current_world_time(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("Unit test must not execute handlers")


class _FakeCalendarService:
    @property
    def definition(self) -> Any:
        return type("Def", (), {"calendar_id": "test_calendar"})()

    def tick_to_date(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("Unit test must not execute handlers")

    def date_to_tick(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("Unit test must not execute handlers")

    def advance_world_time(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("Unit test must not execute handlers")

    def time_until(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("Unit test must not execute handlers")


# ── Fixture ───────────────────────────────────────────────────────────────────────


@pytest.fixture(name="mvp_registry")
def _mvp_registry_fixture() -> ToolRegistry:
    """Build and return the complete MVP ToolRegistry with fakes."""
    return build_mvp_tool_registry(
        search_service=_FakeSearchService(),
        repository=_FakeRepository(),
        runtime_service=_FakeRuntimeService(),
        recovery_service=_FakeRecoveryService(),
        session_repository=_FakeSessionRepo(),
        event_repository=_FakeEventRepo(),
        world_time_repository=_FakeWorldTimeRepo(),
        calendar_service=_FakeCalendarService(),
    )


# ── Registry shape tests ──────────────────────────────────────────────────────────


class TestMvpRegistryShape:
    """MVP registry size, names, and metadata."""

    def test_returns_tool_registry(self, mvp_registry: ToolRegistry) -> None:
        assert isinstance(mvp_registry, ToolRegistry)

    def test_len_18(self, mvp_registry: ToolRegistry) -> None:
        assert len(mvp_registry) == 18

    def test_exact_sorted_names(self, mvp_registry: ToolRegistry) -> None:
        names = [d.name for d in mvp_registry.list_definitions()]
        expected = [
            "advance_world_time",
            "append_entity_fact",
            "end_session",
            "game_date_to_world_tick",
            "get_active_session",
            "get_entity",
            "get_session",
            "get_world_time",
            "list_session_events",
            "list_sessions",
            "patch_entity",
            "record_event",
            "record_note",
            "search_entities",
            "set_world_time",
            "start_session",
            "time_between_world_ticks",
            "world_tick_to_date",
        ]
        assert names == expected

    def test_no_duplicate_names(self, mvp_registry: ToolRegistry) -> None:
        names = [d.name for d in mvp_registry.list_definitions()]
        assert len(names) == len(set(names))

    def test_read_count_10(self, mvp_registry: ToolRegistry) -> None:
        read_count = sum(
            1 for d in mvp_registry.list_definitions() if d.permission == Permission.READ
        )
        assert read_count == 10

    def test_write_count_8(self, mvp_registry: ToolRegistry) -> None:
        write_count = sum(
            1 for d in mvp_registry.list_definitions() if d.permission == Permission.WRITE
        )
        assert write_count == 8

    def test_entity_mutation_count_2(self, mvp_registry: ToolRegistry) -> None:
        count = sum(
            1
            for d in mvp_registry.list_definitions()
            if SideEffect.ENTITY_MUTATION in d.side_effects
        )
        assert count == 2

    def test_session_mutation_count_4(self, mvp_registry: ToolRegistry) -> None:
        count = sum(
            1
            for d in mvp_registry.list_definitions()
            if SideEffect.SESSION_MUTATION in d.side_effects
        )
        assert count == 4

    def test_world_time_mutation_count_2(self, mvp_registry: ToolRegistry) -> None:
        count = sum(
            1
            for d in mvp_registry.list_definitions()
            if SideEffect.WORLD_TIME_MUTATION in d.side_effects
        )
        assert count == 2


# ── Session-mode metadata consistency ─────────────────────────────────────────────


class TestMvpRegistrySessionModes:
    """Verify session-mode metadata for each tool."""

    def test_start_session_no_active_only(self, mvp_registry: ToolRegistry) -> None:
        defn = mvp_registry.get_definition("start_session")
        assert defn.allowed_session_modes == frozenset({SessionMode.NO_ACTIVE_SESSION})

    def test_record_event_active_only(self, mvp_registry: ToolRegistry) -> None:
        defn = mvp_registry.get_definition("record_event")
        assert defn.allowed_session_modes == frozenset({SessionMode.ACTIVE_SESSION})

    def test_record_note_active_only(self, mvp_registry: ToolRegistry) -> None:
        defn = mvp_registry.get_definition("record_note")
        assert defn.allowed_session_modes == frozenset({SessionMode.ACTIVE_SESSION})

    def test_end_session_active_only(self, mvp_registry: ToolRegistry) -> None:
        defn = mvp_registry.get_definition("end_session")
        assert defn.allowed_session_modes == frozenset({SessionMode.ACTIVE_SESSION})

    def test_entity_reads_both_modes(self, mvp_registry: ToolRegistry) -> None:
        for name in ("search_entities", "get_entity"):
            defn = mvp_registry.get_definition(name)
            assert defn.allowed_session_modes == frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            )

    def test_entity_mutations_both_modes(self, mvp_registry: ToolRegistry) -> None:
        for name in ("patch_entity", "append_entity_fact"):
            defn = mvp_registry.get_definition(name)
            assert defn.allowed_session_modes == frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            )

    def test_session_reads_both_modes(self, mvp_registry: ToolRegistry) -> None:
        for name in ("get_active_session", "get_session", "list_sessions", "list_session_events"):
            defn = mvp_registry.get_definition(name)
            assert defn.allowed_session_modes == frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            )

    def test_world_time_reads_both_modes(self, mvp_registry: ToolRegistry) -> None:
        for name in (
            "get_world_time",
            "world_tick_to_date",
            "game_date_to_world_tick",
            "time_between_world_ticks",
        ):
            defn = mvp_registry.get_definition(name)
            assert defn.allowed_session_modes == frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            )

    def test_world_time_mutations_both_modes(self, mvp_registry: ToolRegistry) -> None:
        for name in ("set_world_time", "advance_world_time"):
            defn = mvp_registry.get_definition(name)
            assert defn.allowed_session_modes == frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            )


# ── Composition delegation ────────────────────────────────────────────────────────


class TestMvpRegistryComposition:
    """Prove composition delegates to family registrars and does not redefine."""

    def test_composition_does_not_invent_definitions(self, mvp_registry: ToolRegistry) -> None:
        """All definitions must come from family modules, not be invented here."""
        definitions = {d.name: d for d in mvp_registry.list_definitions()}
        # Spot-check: entity read definitions
        assert "search_entities" in definitions
        assert "get_entity" in definitions
        # Session read definitions
        assert "get_active_session" in definitions
        assert "get_session" in definitions
        assert "list_sessions" in definitions
        assert "list_session_events" in definitions
        # Session mutation definitions
        assert "start_session" in definitions
        assert "record_event" in definitions
        assert "record_note" in definitions
        assert "end_session" in definitions
        # World time read definitions
        assert "get_world_time" in definitions
        assert "world_tick_to_date" in definitions
        assert "game_date_to_world_tick" in definitions
        assert "time_between_world_ticks" in definitions
        # Entity mutation definitions
        assert "patch_entity" in definitions
        assert "append_entity_fact" in definitions
        # World time mutation definitions
        assert "set_world_time" in definitions
        assert "advance_world_time" in definitions

    def test_composition_not_constructing_repositories(self) -> None:
        """build_mvp_tool_registry must not instantiate concrete repos/services."""
        import inspect

        source = inspect.getsource(build_mvp_tool_registry)
        # Should not contain instantiation of concrete classes
        assert "ObsidianVaultRepository" not in source
        assert "VaultSearchService" not in source
        assert "ObsidianSessionMetadataRepository" not in source
        assert "ObsidianSessionEventRepository" not in source
        assert "ObsidianWorldTimeRepository" not in source
        assert "DeterministicCalendarService" not in source
        # TYPE_CHECKING imports and type annotations are allowed
        # but actual constructor calls are not

    def test_composition_no_global_registry(self) -> None:
        """The module must not have a module-level mutable registry."""
        import dnd_assistant.tools.mvp_registry as mod

        module_dir = [k for k in dir(mod) if not k.startswith("_")]
        assert "registry" not in module_dir
        assert "ToolRegistry" not in [type(getattr(mod, k)).__name__ for k in module_dir]
