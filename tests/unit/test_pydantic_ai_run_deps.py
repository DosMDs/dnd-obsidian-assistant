"""Tests for Pydantic AI run dependencies — DndAgentDeps, PreparedDndAgentRun,
DndAgentRunPreparer (PAIM-06).

Test matrix
───────────

| ID       | Scenario                          | Result              |
|----------|-----------------------------------|---------------------|
| DEP-01   | Successful minimal preparation    | PreparedDndAgentRun |
| DEP-02   | Exact AgentContext identity       | is                  |
| DEP-03   | Exact ExecutionContext identity   | is                  |
| DEP-04   | Exposure/snapshot order alignment | names match         |
| DEP-05   | Bridge identity                   | is                  |
| DEP-06   | One fresh DndAgentPolicy          | isinstance          |
| DEP-07   | Empty exposure                    | exposed_tools == () |
| DEP-08   | READ context                      | only READ tools     |
| DEP-09   | WRITE + audit                     | READ + WRITE tools  |
| DEP-10   | WRITE without audit               | WRITE tools excluded|
| DEP-11   | Session-mode filtering            | existing semantics  |
| DEP-12   | Separate preparations distinct    | not is              |
| DEP-13   | Policy isolation                  | fresh batch state   |
| DEP-14   | Same names, different snapshots   | not same snapshot   |
| DEP-15   | Malformed ExecutionContext        | ValidationError      |
| DEP-15a  | Malformed EC — zero builder reads | ValidationError      |
| DEP-16   | Invalid user input                | ValidationError     |
| DEP-17   | Frozen DndAgentDeps               | FrozenInstanceError |
| DEP-18   | Frozen PreparedDndAgentRun        | FrozenInstanceError |
| DEP-19   | No raw services in deps fields    | expected fields     |
| DEP-20   | Constructor validation            | TypeError           |
"""

from __future__ import annotations

import dataclasses
from collections.abc import Sequence
from datetime import UTC, datetime

import pytest

from dnd_assistant.application.agent_context import (
    AgentContext,
    AgentContextBuilder,
)
from dnd_assistant.application.dnd_agent_policy import DndAgentPolicy
from dnd_assistant.application.pydantic_ai_run_deps import (
    DndAgentDeps,
    DndAgentRunPreparer,
    PreparedDndAgentRun,
)
from dnd_assistant.application.pydantic_ai_tool_bridge import (
    PydanticAIToolBridge,
)
from dnd_assistant.errors import ValidationError
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.tools.catalog import ToolRegistrySchema
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import (
    ExecutionContext,
    Permission,
    SessionMode,
)
from tests.support.pydantic_ai_runtime import (
    HandlerCounters,
    make_tool_registry,
)

# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def counters() -> HandlerCounters:
    return HandlerCounters()


@pytest.fixture
def tool_registry(counters: HandlerCounters) -> ToolRegistry:
    return make_tool_registry(counters)


@pytest.fixture
def tool_catalog(tool_registry: ToolRegistry) -> ToolRegistrySchema:
    from dnd_assistant.tools.catalog import build_tool_registry_schema

    return build_tool_registry_schema(tool_registry)


@pytest.fixture
def tool_bridge(tool_registry: ToolRegistry) -> PydanticAIToolBridge:
    return PydanticAIToolBridge(registry=tool_registry)


@pytest.fixture
def context_builder() -> AgentContextBuilder:
    """Return a minimal AgentContextBuilder that returns a fixed context.

    Uses a real builder with minimal mocked dependencies.
    """
    from dnd_assistant.errors import NotFoundError
    from dnd_assistant.retrieval.service import SearchService
    from dnd_assistant.retrieval.types import SearchHit, SearchQuery
    from dnd_assistant.storage.session_events import RawSessionEvent
    from dnd_assistant.storage.session_metadata import RawSessionMetadata
    from dnd_assistant.storage.types import VaultDocument, VaultRepository

    class _StubSearchService(SearchService):
        def search(self, query: SearchQuery, *, limit: int = 5) -> Sequence[SearchHit]:
            return []

    class _StubVaultRepository(VaultRepository):
        def get_entity(self, entity_id: str) -> VaultDocument:
            raise ValueError("unexpected call")

    class _StubSessionRepo:
        def get_active_session(self) -> RawSessionMetadata | None:
            return None

    class _StubEventRepo:
        def list_events(self, session_id: str) -> list[RawSessionEvent]:
            return []

    class _StubWorldTimeRepo:
        def get_current_world_time(self) -> None:
            raise NotFoundError("no world time")

    return AgentContextBuilder(
        search_service=_StubSearchService(),
        vault_repository=_StubVaultRepository(),
        session_repository=_StubSessionRepo(),  # type: ignore[arg-type]
        event_repository=_StubEventRepo(),  # type: ignore[arg-type]
        world_time_repository=_StubWorldTimeRepo(),  # type: ignore[arg-type]
    )


@pytest.fixture
def read_context() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.READ,
        session_mode=SessionMode.NO_ACTIVE_SESSION,
    )


@pytest.fixture
def write_context() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.WRITE,
        session_mode=SessionMode.ACTIVE_SESSION,
        audit=AuditContext(
            operation_id="test-op",
            real_time=datetime.now(UTC),
            source="test",
        ),
    )


@pytest.fixture
def write_context_no_audit() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.WRITE,
        session_mode=SessionMode.ACTIVE_SESSION,
        audit=None,
    )


@pytest.fixture
def preparer(
    context_builder: AgentContextBuilder,
    tool_catalog: ToolRegistrySchema,
    tool_bridge: PydanticAIToolBridge,
) -> DndAgentRunPreparer:
    return DndAgentRunPreparer(
        context_builder=context_builder,
        tool_catalog=tool_catalog,
        tool_bridge=tool_bridge,
    )


# ==============================================================================
# DEP-01 through DEP-06 — Successful preparation
# ==============================================================================


class TestSuccessfulPreparation:
    """DEP-01 through DEP-06: basic successful preparation."""

    def test_dep01_minimal_preparation(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
    ) -> None:
        """Successful minimal preparation returns PreparedDndAgentRun."""
        result = preparer.prepare("test query", execution_context=read_context)
        assert isinstance(result, PreparedDndAgentRun)
        assert isinstance(result.deps, DndAgentDeps)

    def test_dep02_exact_agent_context_identity(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
    ) -> None:
        """prepared.deps.agent_context is the exact object from context_builder.build()."""
        captured: list[AgentContext] = []
        original_build = preparer._context_builder.build

        def spy_build(user_input: str) -> AgentContext:
            ctx = original_build(user_input)
            captured.append(ctx)
            return ctx

        preparer._context_builder.build = spy_build  # type: ignore[method-assign]

        result = preparer.prepare("test query", execution_context=read_context)
        assert len(captured) == 1
        assert result.deps.agent_context is captured[0]

    def test_dep03_exact_execution_context_identity(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
    ) -> None:
        """prepared.deps.execution_context is the supplied context."""
        result = preparer.prepare("test query", execution_context=read_context)
        assert result.deps.execution_context is read_context

    def test_dep04_exposure_snapshot_order_alignment(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
    ) -> None:
        """Exposed tool names match snapshot names in the same order."""
        result = preparer.prepare("test query", execution_context=read_context)
        exposed_names = tuple(t.name for t in result.exposed_tools)
        assert exposed_names == result.deps.tool_snapshot.names

    def test_dep05_bridge_identity(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
    ) -> None:
        """prepared.deps.tool_bridge is the preparer's bridge."""
        result = preparer.prepare("test query", execution_context=read_context)
        assert result.deps.tool_bridge is preparer._tool_bridge

    def test_dep06_one_fresh_policy(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
    ) -> None:
        """prepared.deps.policy is one fresh DndAgentPolicy."""
        result = preparer.prepare("test query", execution_context=read_context)
        assert isinstance(result.deps.policy, DndAgentPolicy)


# ==============================================================================
# DEP-07 through DEP-11 — Exposure tests
# ==============================================================================


class TestExposure:
    """DEP-07 through DEP-11: tool exposure selection."""

    def test_dep07_empty_exposure(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
    ) -> None:
        """Empty exposure is valid — zero tools exposed."""
        from dnd_assistant.tools.catalog import ToolRegistrySchema

        empty_catalog = ToolRegistrySchema(tools=[])
        empty_preparer = DndAgentRunPreparer(
            context_builder=preparer._context_builder,
            tool_catalog=empty_catalog,
            tool_bridge=preparer._tool_bridge,
        )
        result = empty_preparer.prepare("test query", execution_context=read_context)
        assert result.exposed_tools == ()
        assert result.deps.tool_snapshot.names == ()
        assert isinstance(result.deps.policy, DndAgentPolicy)

    def test_dep08_read_context(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
    ) -> None:
        """READ context exposes only READ tools."""
        result = preparer.prepare("test query", execution_context=read_context)
        for tool in result.exposed_tools:
            assert tool.permission is Permission.READ
        assert len(result.exposed_tools) >= 2  # read_alpha, read_beta

    def test_dep09_write_with_audit(
        self,
        preparer: DndAgentRunPreparer,
        write_context: ExecutionContext,
    ) -> None:
        """WRITE + audit exposes READ and WRITE tools."""
        result = preparer.prepare("test query", execution_context=write_context)
        permissions = {t.permission for t in result.exposed_tools}
        assert Permission.READ in permissions
        assert Permission.WRITE in permissions
        assert len(result.exposed_tools) == len(result.deps.tool_snapshot.names)

    def test_dep10_write_without_audit(
        self,
        preparer: DndAgentRunPreparer,
        write_context_no_audit: ExecutionContext,
    ) -> None:
        """WRITE without audit excludes WRITE tools."""
        result = preparer.prepare("test query", execution_context=write_context_no_audit)
        for tool in result.exposed_tools:
            assert tool.permission is Permission.READ
        assert all(t.name != "write_alpha" for t in result.exposed_tools)

    def test_dep11_session_mode_filtering(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
    ) -> None:
        """Session-mode filtering preserves existing selection semantics."""
        result = preparer.prepare("test query", execution_context=read_context)
        for tool in result.exposed_tools:
            assert SessionMode.NO_ACTIVE_SESSION in tool.allowed_session_modes


# ==============================================================================
# DEP-12 through DEP-14 — Fresh-run isolation
# ==============================================================================


class TestFreshRunIsolation:
    """DEP-12 through DEP-14: run isolation."""

    def test_dep12_separate_preparations_distinct(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
    ) -> None:
        """Two prepare() calls produce distinct instances."""
        run_a = preparer.prepare("query a", execution_context=read_context)
        run_b = preparer.prepare("query b", execution_context=read_context)

        assert run_a is not run_b
        assert run_a.deps is not run_b.deps
        assert run_a.deps.tool_snapshot is not run_b.deps.tool_snapshot
        assert run_a.deps.policy is not run_b.deps.policy

    def test_dep13_policy_isolation(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
    ) -> None:
        """Run B's first batch is still admissible after run A consumes its batch."""
        run_a = preparer.prepare("query a", execution_context=read_context)
        run_b = preparer.prepare("query b", execution_context=read_context)

        from pydantic_ai.messages import ToolCallPart

        call_a = ToolCallPart(tool_name="read_alpha", args='{"value": "a"}', tool_call_id="call-a")
        run_a.deps.policy.admit_tool_batch([call_a])

        call_b = ToolCallPart(tool_name="read_beta", args='{"number": 1}', tool_call_id="call-b")
        admission = run_b.deps.policy.admit_tool_batch([call_b])
        assert len(admission.calls) == 1
        assert admission.calls[0].tool_name == "read_beta"

    def test_dep14_same_names_different_snapshots(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
    ) -> None:
        """Same exposed names do not imply same snapshot capability."""
        run_a = preparer.prepare("query a", execution_context=read_context)
        run_b = preparer.prepare("query b", execution_context=read_context)

        assert run_a.deps.tool_snapshot.names == run_b.deps.tool_snapshot.names
        assert run_a.deps.tool_snapshot is not run_b.deps.tool_snapshot


# ==============================================================================
# DEP-15 through DEP-16 — Invalid input tests
# ==============================================================================


class TestInvalidInput:
    """DEP-15 through DEP-16: invalid input handling."""

    def test_dep15_malformed_execution_context(
        self,
        preparer: DndAgentRunPreparer,
    ) -> None:
        """Malformed ExecutionContext raises ValidationError before context reads."""
        with pytest.raises(ValidationError, match="execution_context must be an ExecutionContext"):
            preparer.prepare("test query", execution_context=object())  # type: ignore[arg-type]

    def test_dep15a_malformed_ec_zero_builder_reads(
        self,
        preparer: DndAgentRunPreparer,
    ) -> None:
        """Malformed ExecutionContext causes zero context_builder.build() calls."""
        build_count: list[int] = [0]
        original_build = preparer._context_builder.build

        def counting_build(user_input: str) -> AgentContext:
            build_count[0] += 1
            return original_build(user_input)

        preparer._context_builder.build = counting_build  # type: ignore[method-assign]

        with pytest.raises(ValidationError):
            preparer.prepare("test query", execution_context=object())  # type: ignore[arg-type]

        assert build_count[0] == 0, (
            f"Expected 0 builder calls for malformed EC, got {build_count[0]}"
        )

    def test_dep16_invalid_user_input(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
    ) -> None:
        """Invalid user input raises ValidationError from context builder."""
        with pytest.raises(ValidationError, match="user_input must not be empty"):
            preparer.prepare("", execution_context=read_context)


# ==============================================================================
# DEP-17 through DEP-18 — Frozen containers
# ==============================================================================


class TestFrozenContainers:
    """DEP-17 through DEP-18: frozen dataclass containers."""

    def test_dep17_frozen_dnd_agent_deps(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
    ) -> None:
        """DndAgentDeps top-level assignment raises FrozenInstanceError."""
        result = preparer.prepare("test query", execution_context=read_context)
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.deps.agent_context = object()  # type: ignore[misc]

    def test_dep18_frozen_prepared_run(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
    ) -> None:
        """PreparedDndAgentRun top-level assignment raises FrozenInstanceError."""
        result = preparer.prepare("test query", execution_context=read_context)
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.exposed_tools = ()  # type: ignore[misc]


# ==============================================================================
# DEP-19 — No raw services in deps fields
# ==============================================================================


class TestDepsFieldStructure:
    """DEP-19: structural assertion over DndAgentDeps fields."""

    def test_dep19_no_raw_services_in_deps_fields(
        self,
    ) -> None:
        """DndAgentDeps must not contain raw repositories/services/builders."""
        expected = {"agent_context", "execution_context", "tool_bridge", "tool_snapshot", "policy"}
        actual = {f.name for f in dataclasses.fields(DndAgentDeps)}
        assert actual == expected, (
            f"DndAgentDeps fields mismatch. "
            f"Expected={expected}, Actual={actual}. "
            "No raw repositories, services, or builders allowed."
        )


# ==============================================================================
# DEP-20 — Constructor validation
# ==============================================================================


class TestConstructorValidation:
    """DEP-20: constructor validation."""

    def test_dep20_malformed_context_builder(
        self,
        tool_catalog: ToolRegistrySchema,
        tool_bridge: PydanticAIToolBridge,
    ) -> None:
        """Malformed context_builder raises TypeError."""
        with pytest.raises(TypeError, match="context_builder"):
            DndAgentRunPreparer(
                context_builder=object(),  # type: ignore[arg-type]
                tool_catalog=tool_catalog,
                tool_bridge=tool_bridge,
            )

    def test_dep20_malformed_tool_catalog(
        self,
        context_builder: AgentContextBuilder,
        tool_bridge: PydanticAIToolBridge,
    ) -> None:
        """Malformed tool_catalog raises TypeError."""
        with pytest.raises(TypeError, match="tool_catalog"):
            DndAgentRunPreparer(
                context_builder=context_builder,
                tool_catalog=object(),  # type: ignore[arg-type]
                tool_bridge=tool_bridge,
            )

    def test_dep20_malformed_tool_bridge(
        self,
        context_builder: AgentContextBuilder,
        tool_catalog: ToolRegistrySchema,
    ) -> None:
        """Malformed tool_bridge raises TypeError."""
        with pytest.raises(TypeError, match="tool_bridge"):
            DndAgentRunPreparer(
                context_builder=context_builder,
                tool_catalog=tool_catalog,
                tool_bridge=object(),  # type: ignore[arg-type]
            )


# ==============================================================================
# Import isolation
# ==============================================================================


class TestImportIsolation:
    """Fresh-process import isolation for the new module."""

    def test_fresh_import_does_not_eagerly_load_forbidden_packages(
        self,
    ) -> None:
        """A fresh import must not eagerly load models/storage/retrieval/cli."""
        import subprocess
        import sys

        code = """
import sys

# Import our module
import dnd_assistant.application.pydantic_ai_run_deps

# Check none of the forbidden packages were eagerly loaded
forbidden = [
    'dnd_assistant.models',
    'dnd_assistant.models.ollama',
    'dnd_assistant.storage',
    'dnd_assistant.retrieval',
    'dnd_assistant.cli',
    'pydantic_ai',
]
for mod in forbidden:
    if mod in sys.modules:
        print(f'FAIL: {mod} was eagerly loaded')
        sys.exit(1)

print('PASS')
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, f"Import isolation failed: {result.stderr}"
        assert "PASS" in result.stdout


# ==============================================================================
# PAIM-C10 — Cross-run dependency binding mismatch tests
# ==============================================================================
#
# | Bundle                              | Bridge | Snapshot | Policy | Result          |
# | ----------------------------------- | ------ | -------- | ------ | --------------- |
# | Valid run A                         | A      | A        | A      | PreparedRun OK  |
# | Bridge B + snapshot B + policy A    | B      | B        | A      | ValidationError |
# | Same bridge + snapshot B + policy A | same   | B        | A      | ValidationError |
# | Copied snapshot                     | A      | copy(A)  | A      | ValidationError |


class TestCrossRunBinding:
    """PAIM-C10: cross-run dependency binding mismatch tests."""

    def test_c10_valid_run_a(
        self, preparer: DndAgentRunPreparer, read_context: ExecutionContext
    ) -> None:
        """Valid run A produces a valid PreparedDndAgentRun."""
        run_a = preparer.prepare("query a", execution_context=read_context)
        assert isinstance(run_a, PreparedDndAgentRun)
        assert isinstance(run_a.deps, DndAgentDeps)

    def test_c10_bridge_b_snapshot_b_policy_a(
        self,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Bridge B + snapshot B + policy A raises ValidationError."""
        bridge_a = PydanticAIToolBridge(registry=tool_registry)
        bridge_b = PydanticAIToolBridge(registry=tool_registry)

        preparer_a = DndAgentRunPreparer(
            context_builder=context_builder,
            tool_catalog=tool_catalog,
            tool_bridge=bridge_a,
        )
        preparer_b = DndAgentRunPreparer(
            context_builder=context_builder,
            tool_catalog=tool_catalog,
            tool_bridge=bridge_b,
        )

        run_a = preparer_a.prepare("query a", execution_context=read_context)
        run_b = preparer_b.prepare("query b", execution_context=read_context)

        # Construct invalid deps: bridge_b + snapshot_b + policy_a
        with pytest.raises(ValidationError, match="different tool bridge"):
            DndAgentDeps(
                agent_context=run_b.deps.agent_context,
                execution_context=run_b.deps.execution_context,
                tool_bridge=run_b.deps.tool_bridge,
                tool_snapshot=run_b.deps.tool_snapshot,
                policy=run_a.deps.policy,
            )

    def test_c10_same_bridge_different_snapshot(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
    ) -> None:
        """Same bridge + snapshot B + policy A raises ValidationError."""
        run_a = preparer.prepare("query a", execution_context=read_context)
        run_b = preparer.prepare("query b", execution_context=read_context)

        # Same bridge, different snapshot, policy A
        with pytest.raises(ValidationError, match="different snapshot"):
            DndAgentDeps(
                agent_context=run_b.deps.agent_context,
                execution_context=run_b.deps.execution_context,
                tool_bridge=run_a.deps.tool_bridge,
                tool_snapshot=run_b.deps.tool_snapshot,
                policy=run_a.deps.policy,
            )

    def test_c10_copied_snapshot(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
    ) -> None:
        """Copied/non-issued snapshot raises ValidationError."""
        run_a = preparer.prepare("query a", execution_context=read_context)

        copied_snapshot = dataclasses.replace(run_a.deps.tool_snapshot)

        with pytest.raises(ValidationError, match="not issued"):
            DndAgentDeps(
                agent_context=run_a.deps.agent_context,
                execution_context=run_a.deps.execution_context,
                tool_bridge=run_a.deps.tool_bridge,
                tool_snapshot=copied_snapshot,
                policy=run_a.deps.policy,
            )

    def test_c10_zero_handler_calls(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
        counters: HandlerCounters,
    ) -> None:
        """Cross-run mismatch causes zero handler calls."""
        run_a = preparer.prepare("query a", execution_context=read_context)
        run_b = preparer.prepare("query b", execution_context=read_context)

        with pytest.raises(ValidationError):
            DndAgentDeps(
                agent_context=run_b.deps.agent_context,
                execution_context=run_b.deps.execution_context,
                tool_bridge=run_b.deps.tool_bridge,
                tool_snapshot=run_b.deps.tool_snapshot,
                policy=run_a.deps.policy,
            )

        assert counters.alpha == 0
        assert counters.beta == 0
        assert counters.write_alpha == 0


# ==============================================================================
# PAIM-C10 — PreparedDndAgentRun exposure mismatch tests
# ==============================================================================
#
# | Scenario                                  | Result          |
# | ----------------------------------------- | --------------- |
# | C10-R1 hidden extra public exposure       | ValidationError |
# | C10-R2 missing public exposure            | ValidationError |
# | C10-R3 reordered exposure                 | ValidationError |


class TestPreparedRunExposure:
    """PAIM-C10: PreparedDndAgentRun exposure consistency."""

    def test_c10_r1_extra_exposure(
        self,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Extra exposed tool not in snapshot raises ValidationError."""
        bridge = PydanticAIToolBridge(registry=tool_registry)
        preparer_obj = DndAgentRunPreparer(
            context_builder=context_builder,
            tool_catalog=tool_catalog,
            tool_bridge=bridge,
        )
        run = preparer_obj.prepare("query", execution_context=read_context)

        from dnd_assistant.tools.catalog import ToolPublicDefinition

        # Build extra exposure with a tool not in the snapshot
        extra_tools = list(run.exposed_tools)
        extra_tools.append(
            ToolPublicDefinition(
                name="nonexistent_tool",
                description="Not in snapshot",
                input_schema={"type": "object", "properties": {}},
                output_schema={"type": "object", "properties": {}},
                permission=run.exposed_tools[0].permission,
                side_effects=list(run.exposed_tools[0].side_effects),
                allowed_session_modes=list(run.exposed_tools[0].allowed_session_modes),
            )
        )

        with pytest.raises(ValidationError, match="do not match"):
            PreparedDndAgentRun(
                deps=run.deps,
                exposed_tools=tuple(extra_tools),
            )

    def test_c10_r2_missing_exposure(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
    ) -> None:
        """Missing exposed tool raises ValidationError."""
        run = preparer.prepare("query", execution_context=read_context)

        missing_tools = run.exposed_tools[:-1]  # drop last tool

        with pytest.raises(ValidationError, match="do not match"):
            PreparedDndAgentRun(
                deps=run.deps,
                exposed_tools=missing_tools,
            )

    def test_c10_r3_reordered_exposure(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
    ) -> None:
        """Reordered exposed tools raise ValidationError."""
        run = preparer.prepare("query", execution_context=read_context)

        reordered = tuple(reversed(run.exposed_tools))

        with pytest.raises(ValidationError, match="do not match"):
            PreparedDndAgentRun(
                deps=run.deps,
                exposed_tools=reordered,
            )

    def test_c10_r3_zero_handler_calls(
        self,
        preparer: DndAgentRunPreparer,
        read_context: ExecutionContext,
        counters: HandlerCounters,
    ) -> None:
        """Exposure mismatch causes zero handler calls."""
        run = preparer.prepare("query", execution_context=read_context)
        reordered = tuple(reversed(run.exposed_tools))

        with pytest.raises(ValidationError):
            PreparedDndAgentRun(
                deps=run.deps,
                exposed_tools=reordered,
            )

        assert counters.alpha == 0
        assert counters.beta == 0
        assert counters.write_alpha == 0
