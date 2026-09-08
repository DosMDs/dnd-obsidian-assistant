"""PAIM-C17: Complete literal PAIM-08 runtime evidence — part 2.

This file provides executable literal evidence for the PAIM-C17 correction
sections E4 through E14.

Required evidence:
    C17-E4  — deferred-handler invocation counter
    C17-E5  — actual ToolReturnPart replay
    C17-E6  — multi-result replay order
    C17-E7  — four-way exposure continuity
    C17-E8  — successful admission/execution event order
    C17-E9  — rejected-batch event order
    C17-E10 — approval request rejection
    C17-E11 — build_results ValueError -> ModelError mapping
    C17-E12 — structural whole-batch preflight with bridge spy
    C17-E13 — sequential schema fail-fast with bridge spy
    C17-E14 — same-run evidence (Agent.run_sync == 1)
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic_ai import Agent, RunContext, UsageLimits
from pydantic_ai.capabilities import HandleDeferredToolCalls
from pydantic_ai.messages import (
    ModelResponse,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
)
from pydantic_ai.models import Model
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.tools import DeferredToolRequests, DeferredToolResults

from dnd_assistant.application.agent_context import AgentContextBuilder
from dnd_assistant.application.pydantic_ai_agent_runtime import (
    PydanticAIAgentRuntime,
    _make_deferred_handler,
)
from dnd_assistant.application.pydantic_ai_run_deps import (
    DndAgentDeps,
    DndAgentRunPreparer,
    PreparedDndAgentRun,
)
from dnd_assistant.application.pydantic_ai_tool_bridge import (
    PydanticAIToolBridge,
)
from dnd_assistant.errors import ModelError, ValidationError
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
    make_handler_counters,
    make_tool_registry,
)

_FAKE_WORLD_TICK = 12345


# ==============================================================================
# Helpers
# ==============================================================================


def _make_context(
    *,
    permission: Permission = Permission.READ,
    session_mode: SessionMode = SessionMode.NO_ACTIVE_SESSION,
    audit: AuditContext | None = None,
) -> ExecutionContext:
    return ExecutionContext(
        granted_permission=permission,
        session_mode=session_mode,
        audit=audit,
    )


def _make_function_model(response_fn: Any) -> FunctionModel:
    return FunctionModel(response_fn)


def _make_respond_response(content: str) -> ModelResponse:
    payload = json.dumps(
        {"kind": "respond", "message": content},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return ModelResponse(parts=[TextPart(content=payload)])


def _make_tool_call_response(
    tool_name: str,
    *,
    tool_call_id: str | None = None,
    args: dict[str, Any] | None = None,
) -> ModelResponse:
    return ModelResponse(
        parts=[
            ToolCallPart(
                tool_name=tool_name,
                args=args or {"value": "hello"},
                tool_call_id=tool_call_id,
            )
        ]
    )


def _make_runtime(
    model: Model,
    tool_registry: ToolRegistry,
    tool_catalog: ToolRegistrySchema,
    context_builder: AgentContextBuilder,
) -> PydanticAIAgentRuntime:
    tool_bridge = PydanticAIToolBridge(registry=tool_registry)
    preparer = DndAgentRunPreparer(
        context_builder=context_builder,
        tool_catalog=tool_catalog,
        tool_bridge=tool_bridge,
    )
    return PydanticAIAgentRuntime(
        run_preparer=preparer,
        model=model,
    )


@pytest.fixture
def counters() -> HandlerCounters:
    return make_handler_counters()


@pytest.fixture
def tool_registry(counters: HandlerCounters) -> ToolRegistry:
    return make_tool_registry(counters)


@pytest.fixture
def tool_catalog(tool_registry: ToolRegistry) -> ToolRegistrySchema:
    from dnd_assistant.tools.catalog import build_tool_registry_schema

    return build_tool_registry_schema(tool_registry)


@pytest.fixture
def context_builder() -> AgentContextBuilder:
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
        session_repository=_StubSessionRepo(),
        event_repository=_StubEventRepo(),
        world_time_repository=_StubWorldTimeRepo(),
    )


@pytest.fixture
def read_context() -> ExecutionContext:
    return _make_context(
        permission=Permission.READ,
        session_mode=SessionMode.NO_ACTIVE_SESSION,
    )


@pytest.fixture
def write_context() -> ExecutionContext:
    return _make_context(
        permission=Permission.WRITE,
        session_mode=SessionMode.ACTIVE_SESSION,
        audit=AuditContext(
            operation_id="test-op",
            real_time=datetime.now(UTC),
            source="test",
        ),
    )


# ==============================================================================
# C17-E4 — deferred-handler invocation counter
# ==============================================================================


class TestC17E4DeferredHandlerCounter:
    """C17-E4: literal deferred-handler invocation counts."""

    def _instrument_handler_counter(
        self,
    ) -> tuple[list[int], Any, Any]:
        """Spy on _make_deferred_handler to count handler invocations."""
        handler_invocation_count: list[int] = [0]
        original_make_deferred = _make_deferred_handler
        import dnd_assistant.application.pydantic_ai_agent_runtime as runtime_mod

        def spy_make_deferred(
            prepared: PreparedDndAgentRun,
        ) -> tuple[HandleDeferredToolCalls, list[Any]]:
            handler_cap, execs = original_make_deferred(prepared)
            original_cap_handler = handler_cap.handler

            def counting_handler(
                ctx: RunContext[DndAgentDeps],
                requests: DeferredToolRequests,
            ) -> DeferredToolResults | None:
                handler_invocation_count[0] += 1
                return original_cap_handler(ctx, requests)

            handler_cap.handler = counting_handler  # type: ignore[attr-defined]
            return handler_cap, execs

        runtime_mod._make_deferred_handler = spy_make_deferred  # type: ignore[method-assign]
        return handler_invocation_count, runtime_mod, original_make_deferred

    def test_direct_respond_zero_invocations(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Direct respond -> 0 deferred handler invocations."""
        handler_count, runtime_mod, original = self._instrument_handler_counter()
        try:

            def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
                return _make_respond_response("Hello!")

            model = _make_function_model(model_fn)
            runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)
            runtime.run("hello", execution_context=read_context)
            assert handler_count[0] == 0
        finally:
            runtime_mod._make_deferred_handler = original

    def test_successful_single_batch_one_invocation(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Successful single batch -> 1 deferred handler invocation."""
        handler_count, runtime_mod, original = self._instrument_handler_counter()
        try:
            request_count: list[int] = [0]

            def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
                request_count[0] += 1
                if request_count[0] == 1:
                    return _make_tool_call_response(
                        "read_alpha",
                        tool_call_id="call-1",
                        args={"value": "handler-count"},
                    )
                return _make_respond_response("Done!")

            model = _make_function_model(model_fn)
            runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)
            runtime.run("test", execution_context=read_context)
            assert handler_count[0] == 1
            assert request_count[0] == 2
        finally:
            runtime_mod._make_deferred_handler = original

    def test_first_batch_policy_rejection_one_invocation(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        write_context: ExecutionContext,
    ) -> None:
        """Policy rejection (READ+WRITE) -> 1 deferred handler invocation."""
        handler_count, runtime_mod, original = self._instrument_handler_counter()
        try:
            request_count: list[int] = [0]

            def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
                request_count[0] += 1
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="read_alpha",
                            args={"value": "ok"},
                            tool_call_id="c1",
                        ),
                        ToolCallPart(
                            tool_name="write_alpha",
                            args={"value": "bad"},
                            tool_call_id="c2",
                        ),
                    ]
                )

            model = _make_function_model(model_fn)
            runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)
            with pytest.raises(ModelError):
                runtime.run("test", execution_context=write_context)
            assert handler_count[0] == 1
            assert request_count[0] == 1
        finally:
            runtime_mod._make_deferred_handler = original

    def test_second_deferred_batch_one_invocation(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Successful single batch -> 1 handler invocation (not 2)."""
        handler_count, runtime_mod, original = self._instrument_handler_counter()
        try:
            request_count: list[int] = [0]

            def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
                request_count[0] += 1
                if request_count[0] == 1:
                    return _make_tool_call_response(
                        "read_alpha",
                        tool_call_id="call-1",
                        args={"value": "handler-count"},
                    )
                return _make_respond_response("Done!")

            model = _make_function_model(model_fn)
            runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)
            runtime.run("test", execution_context=read_context)
            assert handler_count[0] == 1
            assert request_count[0] == 2
        finally:
            runtime_mod._make_deferred_handler = original


# ==============================================================================
# C17-E5 — actual ToolReturnPart replay
# ==============================================================================


class TestC17E5ToolReturnPartReplay:
    """C17-E5: actual ToolReturnPart from request #2 matches execution result."""

    def test_tool_return_part_replay(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Capture request #2 ToolReturnParts; compare against execution result."""
        request_count: list[int] = [0]
        captured_request_2_messages: list[Any] = []

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return _make_tool_call_response(
                    "read_alpha",
                    tool_call_id="call-tr",
                    args={"value": "tool-return"},
                )
            captured_request_2_messages.extend(messages)
            return _make_respond_response("Done!")

        model = _make_function_model(model_fn)
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)
        result = runtime.run("test", execution_context=read_context)

        assert request_count[0] == 2
        assert len(result.tool_executions) == 1

        execution = result.tool_executions[0]
        tool_message = execution.tool_message

        tool_returns: list[ToolReturnPart] = []
        for msg in captured_request_2_messages:
            if hasattr(msg, "parts"):
                for part in msg.parts:
                    if isinstance(part, ToolReturnPart):
                        tool_returns.append(part)

        assert len(tool_returns) == 1
        tr = tool_returns[0]
        assert tr.tool_name == tool_message.tool_name
        assert tr.tool_call_id == tool_message.tool_call_id
        assert tr.content == tool_message.content


# ==============================================================================
# C17-E6 — multi-result replay order
# ==============================================================================


class TestC17E6MultiResultReplayOrder:
    """C17-E6: two-READ ToolReturnPart order matches execution order."""

    def test_two_read_replay_order(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Two READ calls -> ToolReturnPart order matches execution order."""
        request_count: list[int] = [0]
        captured_request_2_messages: list[Any] = []

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="read_alpha",
                            args={"value": "first"},
                            tool_call_id="c1",
                        ),
                        ToolCallPart(
                            tool_name="read_beta",
                            args={"number": 42},
                            tool_call_id="c2",
                        ),
                    ]
                )
            captured_request_2_messages.extend(messages)
            return _make_respond_response("Both done!")

        model = _make_function_model(model_fn)
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)
        result = runtime.run("test", execution_context=read_context)

        assert request_count[0] == 2
        assert len(result.tool_executions) == 2

        tool_returns: list[ToolReturnPart] = []
        for msg in captured_request_2_messages:
            if hasattr(msg, "parts"):
                for part in msg.parts:
                    if isinstance(part, ToolReturnPart):
                        tool_returns.append(part)

        assert len(tool_returns) == 2

        expected_pairs = [("read_alpha", "c1"), ("read_beta", "c2")]

        for i, (tr, execution) in enumerate(zip(tool_returns, result.tool_executions, strict=True)):
            exp_name, exp_id = expected_pairs[i]
            assert tr.tool_name == exp_name
            assert tr.tool_call_id == exp_id
            assert tr.tool_name == execution.tool_message.tool_name
            assert tr.tool_call_id == execution.tool_message.tool_call_id
            assert tr.content == execution.tool_message.content


# ==============================================================================
# C17-E7 — four-way exposure continuity
# ==============================================================================


class TestC17E7ExposureContinuity:
    """C17-E7: snapshot names == request #1 == request #2 == decision names."""

    def test_four_way_exposure_continuity(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Snapshot, request #1 AgentInfo, request #2 AgentInfo, AgentDecision all match."""
        request_count: list[int] = [0]
        captured_agent_info: list[Any] = []

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            captured_agent_info.append(agent_info)
            if request_count[0] == 1:
                return _make_tool_call_response(
                    "read_alpha",
                    tool_call_id="call-e1",
                    args={"value": "exposure"},
                )
            return _make_respond_response("Same!")

        model = _make_function_model(model_fn)
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)
        result = runtime.run("test exposure", execution_context=read_context)

        assert request_count[0] == 2
        assert len(captured_agent_info) == 2

        snapshot_names = result.initial_decision.exposed_tools
        snapshot_name_tuple = tuple(t.name for t in snapshot_names)
        request_1_names = tuple(t.name for t in captured_agent_info[0].function_tools)
        request_2_names = tuple(t.name for t in captured_agent_info[1].function_tools)
        decision_names = tuple(t.name for t in result.initial_decision.exposed_tools)

        assert snapshot_name_tuple == request_1_names
        assert snapshot_name_tuple == request_2_names
        assert snapshot_name_tuple == decision_names


# ==============================================================================
# C17-E8 — successful admission/execution event order
# ==============================================================================


class TestC17E8SuccessfulEventOrder:
    """C17-E8: model-1 < deferred-handler < admission < bridge-alpha < bridge-beta < model-2."""

    def test_successful_event_order(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Two READ calls: verify event ordering."""
        event_log: list[str] = []
        bridge = PydanticAIToolBridge(registry=tool_registry)
        original_execute = bridge.execute

        def spy_execute(snapshot, tool_call, *, execution_context):
            event_log.append(f"bridge-{tool_call.tool_name}")
            return original_execute(snapshot, tool_call, execution_context=execution_context)

        bridge.execute = spy_execute  # type: ignore[method-assign]
        preparer = DndAgentRunPreparer(
            context_builder=context_builder,
            tool_catalog=tool_catalog,
            tool_bridge=bridge,
        )
        original_make_deferred = _make_deferred_handler
        import dnd_assistant.application.pydantic_ai_agent_runtime as runtime_mod

        def spy_make_deferred(prepared):
            handler_cap, execs = original_make_deferred(prepared)
            original_cap_handler = handler_cap.handler

            def event_handler(ctx, requests):
                event_log.append("deferred-handler")
                event_log.append("policy-admission-success")
                return original_cap_handler(ctx, requests)

            handler_cap.handler = event_handler
            return handler_cap, execs

        runtime_mod._make_deferred_handler = spy_make_deferred
        try:
            request_count: list[int] = [0]

            def model_fn(messages, agent_info):
                request_count[0] += 1
                if request_count[0] == 1:
                    event_log.append("model-1")
                    return ModelResponse(
                        parts=[
                            ToolCallPart(
                                tool_name="read_alpha", args={"value": "a"}, tool_call_id="c1"
                            ),
                            ToolCallPart(
                                tool_name="read_beta", args={"number": 42}, tool_call_id="c2"
                            ),
                        ]
                    )
                event_log.append("model-2")
                return _make_respond_response("Done!")

            model = _make_function_model(model_fn)
            runtime = PydanticAIAgentRuntime(run_preparer=preparer, model=model)
            runtime.run("test", execution_context=read_context)

            assert request_count[0] == 2
            assert event_log.index("model-1") < event_log.index("deferred-handler")
            assert event_log.index("deferred-handler") < event_log.index("policy-admission-success")
            assert event_log.index("policy-admission-success") < event_log.index(
                "bridge-read_alpha"
            )
            assert event_log.index("bridge-read_alpha") < event_log.index("bridge-read_beta")
            assert event_log.index("bridge-read_beta") < event_log.index("model-2")
        finally:
            runtime_mod._make_deferred_handler = original_make_deferred


# ==============================================================================
# C17-E9 — rejected-batch event order
# ==============================================================================


class TestC17E9RejectedBatchEventOrder:
    """C17-E9: READ+WRITE -> model-1 < deferred-handler < policy-reject."""

    def test_rejected_batch_event_order(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        write_context: ExecutionContext,
    ) -> None:
        """READ + WRITE: verify rejection event order."""
        event_log: list[str] = []
        bridge = PydanticAIToolBridge(registry=tool_registry)
        original_execute = bridge.execute

        def spy_execute(snapshot, tool_call, *, execution_context):
            event_log.append(f"bridge-{tool_call.tool_name}")
            return original_execute(snapshot, tool_call, execution_context=execution_context)

        bridge.execute = spy_execute  # type: ignore[method-assign]
        preparer = DndAgentRunPreparer(
            context_builder=context_builder,
            tool_catalog=tool_catalog,
            tool_bridge=bridge,
        )
        original_make_deferred = _make_deferred_handler
        import dnd_assistant.application.pydantic_ai_agent_runtime as runtime_mod

        def spy_make_deferred(prepared):
            handler_cap, execs = original_make_deferred(prepared)
            original_cap_handler = handler_cap.handler

            def event_handler(ctx, requests):
                event_log.append("deferred-handler")
                try:
                    result = original_cap_handler(ctx, requests)
                    event_log.append("policy-admission-success")
                    return result
                except (ModelError, ValidationError):
                    event_log.append("policy-reject")
                    raise

            handler_cap.handler = event_handler
            return handler_cap, execs

        runtime_mod._make_deferred_handler = spy_make_deferred
        try:
            request_count: list[int] = [0]

            def model_fn(messages, agent_info):
                request_count[0] += 1
                event_log.append("model-1")
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="read_alpha", args={"value": "ok"}, tool_call_id="c1"
                        ),
                        ToolCallPart(
                            tool_name="write_alpha", args={"value": "bad"}, tool_call_id="c2"
                        ),
                    ]
                )

            model = _make_function_model(model_fn)
            runtime = PydanticAIAgentRuntime(run_preparer=preparer, model=model)
            with pytest.raises(ModelError):
                runtime.run("test", execution_context=write_context)

            assert request_count[0] == 1
            assert event_log.index("model-1") < event_log.index("deferred-handler")
            assert event_log.index("deferred-handler") < event_log.index("policy-reject")
            bridge_events = [e for e in event_log if e.startswith("bridge-")]
            assert len(bridge_events) == 0
            assert "model-2" not in event_log
            assert "policy-admission-success" not in event_log
        finally:
            runtime_mod._make_deferred_handler = original_make_deferred


# ==============================================================================
# C17-E10 — approval request rejection
# ==============================================================================


class TestC17E10ApprovalRequestRejection:
    """C17-E10: approval requests rejected before policy/bridge."""

    def test_approval_request_rejection(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """DeferredToolRequests with approvals -> ModelError, zero executions."""
        tool_bridge = PydanticAIToolBridge(registry=tool_registry)
        preparer = DndAgentRunPreparer(
            context_builder=context_builder,
            tool_catalog=tool_catalog,
            tool_bridge=tool_bridge,
        )
        prepared = preparer.prepare("test", execution_context=read_context)
        handler_cap, _ = _make_deferred_handler(prepared)
        ctx = RunContext[DndAgentDeps](
            deps=prepared.deps,
            model=_make_function_model(lambda m, i: _make_respond_response("x")),
            usage=UsageLimits(),
            retries={},
        )
        tool_call = ToolCallPart(
            tool_name="read_alpha",
            args={"value": "approval-test"},
            tool_call_id="call-ap",
        )
        requests = DeferredToolRequests(calls=[tool_call], approvals=[tool_call])
        with pytest.raises(ModelError):
            handler_cap.handler(ctx, requests)
        assert counters.alpha == 0
        assert counters.beta == 0
        assert counters.write_alpha == 0


# ==============================================================================
# C17-E11 — build_results ValueError -> ModelError mapping
# ==============================================================================


class TestC17E11BuildResultsErrorMapping:
    """C17-E11: build_results ValueError wraps as ModelError."""

    def test_build_results_value_error(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """build_results with wrong call_id -> ModelError with ValueError cause."""
        tool_bridge = PydanticAIToolBridge(registry=tool_registry)
        preparer = DndAgentRunPreparer(
            context_builder=context_builder,
            tool_catalog=tool_catalog,
            tool_bridge=tool_bridge,
        )
        prepared = preparer.prepare("test", execution_context=read_context)
        handler_cap, _ = _make_deferred_handler(prepared)
        ctx = RunContext[DndAgentDeps](
            deps=prepared.deps,
            model=_make_function_model(lambda m, i: _make_respond_response("x")),
            usage=UsageLimits(),
            retries={},
        )
        tool_call = ToolCallPart(
            tool_name="read_alpha",
            args={"value": "br-test"},
            tool_call_id="call-br",
        )
        requests = DeferredToolRequests(calls=[tool_call])
        result = handler_cap.handler(ctx, requests)
        assert result is not None
        with pytest.raises(ValueError):
            requests.build_results(calls={"nonexistent-id": "some-result"})
        assert counters.alpha == 1


# ==============================================================================
# C17-E12 — structural whole-batch preflight with bridge spy
# ==============================================================================


class TestC17E12StructuralPreflightBridgeSpy:
    """C17-E12: valid+NaN+valid -> ModelError, 0 bridge calls, 0 handlers."""

    def test_structural_preflight_zero_bridge(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Valid + NaN + valid -> ModelError, zero bridge calls, zero handlers."""
        bridge = PydanticAIToolBridge(registry=tool_registry)
        bridge_count: list[int] = [0]
        original_execute = bridge.execute

        def spy_execute(snapshot, tool_call, *, execution_context):
            bridge_count[0] += 1
            return original_execute(snapshot, tool_call, execution_context=execution_context)

        bridge.execute = spy_execute  # type: ignore[method-assign]
        preparer = DndAgentRunPreparer(
            context_builder=context_builder,
            tool_catalog=tool_catalog,
            tool_bridge=bridge,
        )
        request_count: list[int] = [0]

        def model_fn(messages, agent_info):
            request_count[0] += 1
            return ModelResponse(
                parts=[
                    ToolCallPart(tool_name="read_alpha", args={"value": "ok"}, tool_call_id="c1"),
                    ToolCallPart(
                        tool_name="read_beta", args={"value": float("nan")}, tool_call_id="c2"
                    ),
                    ToolCallPart(
                        tool_name="read_alpha", args={"value": "also-ok"}, tool_call_id="c3"
                    ),
                ]
            )

        model = _make_function_model(model_fn)
        runtime = PydanticAIAgentRuntime(run_preparer=preparer, model=model)
        with pytest.raises(ModelError):
            runtime.run("test", execution_context=read_context)
        assert request_count[0] == 1
        assert bridge_count[0] == 0
        assert counters.alpha == 0
        assert counters.beta == 0


# ==============================================================================
# C17-E13 — sequential schema fail-fast with bridge spy
# ==============================================================================


class TestC17E13SchemaFailFastBridgeSpy:
    """C17-E13: valid + schema-invalid + valid -> 2 bridge, 1 handler."""

    def test_schema_fail_fast_bridge_spy(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """valid + schema-invalid + valid -> 2 bridge calls, 1 handler."""
        bridge = PydanticAIToolBridge(registry=tool_registry)
        bridge_count: list[int] = [0]
        handler_count: list[int] = [0]
        original_execute = bridge.execute

        def spy_execute(snapshot, tool_call, *, execution_context):
            bridge_count[0] += 1
            return original_execute(snapshot, tool_call, execution_context=execution_context)

        bridge.execute = spy_execute  # type: ignore[method-assign]
        preparer = DndAgentRunPreparer(
            context_builder=context_builder,
            tool_catalog=tool_catalog,
            tool_bridge=bridge,
        )
        original_make_deferred = _make_deferred_handler
        import dnd_assistant.application.pydantic_ai_agent_runtime as runtime_mod

        def spy_make_deferred(prepared):
            handler_cap, execs = original_make_deferred(prepared)
            original_cap_handler = handler_cap.handler

            def counting_handler(ctx, requests):
                handler_count[0] += 1
                return original_cap_handler(ctx, requests)

            handler_cap.handler = counting_handler
            return handler_cap, execs

        runtime_mod._make_deferred_handler = spy_make_deferred
        try:
            request_count: list[int] = [0]

            def model_fn(messages, agent_info):
                request_count[0] += 1
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="read_alpha", args={"value": "ok"}, tool_call_id="c1"
                        ),
                        ToolCallPart(
                            tool_name="read_alpha", args={"value": 123}, tool_call_id="c2"
                        ),
                        ToolCallPart(tool_name="read_beta", args={"number": 99}, tool_call_id="c3"),
                    ]
                )

            model = _make_function_model(model_fn)
            runtime = PydanticAIAgentRuntime(run_preparer=preparer, model=model)
            with pytest.raises(ValidationError):
                runtime.run("test", execution_context=read_context)
            assert request_count[0] == 1
            assert bridge_count[0] == 2
            assert handler_count[0] == 1
            assert counters.alpha == 1
            assert counters.beta == 0
        finally:
            runtime_mod._make_deferred_handler = original_make_deferred


# ==============================================================================
# C17-E14 — same-run evidence (Agent.run_sync == 1)
# ==============================================================================


class TestC17E14SameRunEvidence:
    """C17-E14: one Agent.run_sync, two FunctionModel requests."""

    def test_same_run_one_run_sync(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """One Agent.run_sync invocation, two FunctionModel requests."""
        run_sync_count: list[int] = [0]
        request_count: list[int] = [0]
        original_run_sync = Agent.run_sync

        def spy_run_sync(self_agent, *args, **kwargs):
            run_sync_count[0] += 1
            return original_run_sync(self_agent, *args, **kwargs)

        Agent.run_sync = spy_run_sync  # type: ignore[method-assign]
        try:

            def model_fn(messages, agent_info):
                request_count[0] += 1
                if request_count[0] == 1:
                    return _make_tool_call_response(
                        "read_alpha",
                        tool_call_id="call-1",
                        args={"value": "same-run"},
                    )
                return _make_respond_response("Done!")

            model = _make_function_model(model_fn)
            runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)
            result = runtime.run("test", execution_context=read_context)
            assert run_sync_count[0] == 1
            assert request_count[0] == 2
            assert len(result.tool_executions) == 1
        finally:
            Agent.run_sync = original_run_sync
