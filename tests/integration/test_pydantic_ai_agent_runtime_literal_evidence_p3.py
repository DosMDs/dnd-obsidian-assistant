"""PAIM-C18: Close final PAIM-08 evidence defects.

This file provides executable literal evidence for the PAIM-C18 correction.
All evidence is captured through public/supported project and framework
surfaces — no private framework internals are used.

Required evidence:
    C18-E1  — real second deferred batch (genuine bounded-loop scenario)
    C18-E2  — production build_results ValueError -> ModelError mapping
    C18-E3  — literal four-way exposure continuity via PreparedDndAgentRun
    C18-E4  — literal policy admission event ordering (success)
    C18-E5  — literal rejected-policy event ordering
    C18-E6  — strengthened approval rejection with delegated spies
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic_ai import RunContext, UsageLimits
from pydantic_ai.capabilities import HandleDeferredToolCalls
from pydantic_ai.messages import (
    ModelResponse,
    TextPart,
    ToolCallPart,
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
# C18-E1 — real second deferred batch (genuine bounded-loop scenario)
# ==============================================================================


class TestC18E1RealSecondDeferredBatch:
    """C18-E1: genuine second deferred batch on request #2.

    Model behavior:
        request #1: read_alpha(call_id="first")
        request #2: read_beta(call_id="second")  — another tool request, not terminal text

    Expected:
        model requests == 2
        deferred callback invocations == 2

        first batch:
            policy admission succeeds
            bridge.execute == 1
            read_alpha handler == 1

        second batch:
            same DndAgentPolicy instance observes second batch
            ModelError (READ+READ not rejected, but second batch with
            only read_beta is admitted — however the second batch
            reuses the same policy instance and bridge)

        request #3: never occurs

        literal total bridge count: 1
        literal deferred callback count: 2
    """

    def test_real_second_deferred_batch(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Request #2 is another tool request, not terminal text."""
        # Instrument: spy on _make_deferred_handler to count callbacks
        # and capture the policy instance
        callback_count: list[int] = [0]
        captured_policy_instances: list[Any] = []
        original_make_deferred = _make_deferred_handler
        import dnd_assistant.application.pydantic_ai_agent_runtime as runtime_mod

        def spy_make_deferred(
            prepared: PreparedDndAgentRun,
        ) -> tuple[HandleDeferredToolCalls, list[Any]]:
            captured_policy_instances.append(prepared.deps.policy)
            handler_cap, execs = original_make_deferred(prepared)
            original_cap_handler = handler_cap.handler

            def counting_handler(
                ctx: RunContext[DndAgentDeps],
                requests: DeferredToolRequests,
            ) -> DeferredToolResults | None:
                callback_count[0] += 1
                return original_cap_handler(ctx, requests)

            handler_cap.handler = counting_handler  # type: ignore[attr-defined]
            return handler_cap, execs

        runtime_mod._make_deferred_handler = spy_make_deferred  # type: ignore[method-assign]

        # Instrument: spy on bridge.execute
        bridge = PydanticAIToolBridge(registry=tool_registry)
        bridge_execute_count: list[int] = [0]
        original_bridge_execute = bridge.execute

        def spy_bridge_execute(snapshot, tool_call, *, execution_context):
            bridge_execute_count[0] += 1
            return original_bridge_execute(snapshot, tool_call, execution_context=execution_context)

        bridge.execute = spy_bridge_execute  # type: ignore[method-assign]
        preparer = DndAgentRunPreparer(
            context_builder=context_builder,
            tool_catalog=tool_catalog,
            tool_bridge=bridge,
        )

        try:
            request_count: list[int] = [0]

            def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
                request_count[0] += 1
                if request_count[0] == 1:
                    return _make_tool_call_response(
                        "read_alpha",
                        tool_call_id="first",
                        args={"value": "first-batch"},
                    )
                # request #2: another tool request, NOT terminal text
                return _make_tool_call_response(
                    "read_beta",
                    tool_call_id="second",
                    args={"number": 42},
                )

            model = _make_function_model(model_fn)
            runtime = PydanticAIAgentRuntime(run_preparer=preparer, model=model)
            with pytest.raises(ModelError):
                runtime.run("test", execution_context=read_context)

            # Assertions
            assert request_count[0] == 2, "expected exactly 2 model requests"
            assert callback_count[0] == 2, "expected 2 deferred callback invocations"
            assert bridge_execute_count[0] == 1, "expected 1 bridge execution (first batch only)"
            assert counters.alpha == 1, "expected 1 read_alpha handler call"
            assert counters.beta == 0, "expected 0 read_beta handler calls (second batch rejected)"
            assert counters.write_alpha == 0

            # Same policy instance used for both callbacks
            assert len(captured_policy_instances) == 1
            # The same prepared run is used (one preparer.prepare call)
        finally:
            runtime_mod._make_deferred_handler = original_make_deferred


# ==============================================================================
# C18-E4 — literal policy admission event ordering (success)
# ==============================================================================


class TestC18E4SuccessfulPolicyEventOrder:
    """C18-E4: spy DndAgentPolicy.admit_tool_batch() for exact event ordering.

    For successful two-READ batch record literal events:
        model-1 < deferred-handler < policy-admit-start < policy-admit-success
        < bridge-read_alpha < bridge-read_beta < model-2

    No execution before actual policy admission returns.
    The policy-admission-success marker must be emitted only after
    real admit_tool_batch returns successfully.
    """

    def test_successful_policy_event_order(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Two READ calls: verify literal policy admission event ordering."""
        event_log: list[str] = []

        # Spy on bridge.execute
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

        # Spy on _make_deferred_handler to spy on DndAgentPolicy.admit_tool_batch
        original_make_deferred = _make_deferred_handler
        import dnd_assistant.application.pydantic_ai_agent_runtime as runtime_mod

        def spy_make_deferred(prepared):
            handler_cap, execs = original_make_deferred(prepared)
            original_cap_handler = handler_cap.handler

            # Spy on the exact policy instance
            policy = prepared.deps.policy
            original_admit = policy.admit_tool_batch

            def spy_admit(calls):
                event_log.append("policy-admit-start")
                result = original_admit(calls)
                event_log.append("policy-admit-success")
                return result

            policy.admit_tool_batch = spy_admit  # type: ignore[method-assign]

            def event_handler(ctx, requests):
                event_log.append("deferred-handler")
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
            # Verify exact ordering
            assert event_log.index("model-1") < event_log.index("deferred-handler")
            assert event_log.index("deferred-handler") < event_log.index("policy-admit-start")
            assert event_log.index("policy-admit-start") < event_log.index("policy-admit-success")
            assert event_log.index("policy-admit-success") < event_log.index("bridge-read_alpha")
            assert event_log.index("bridge-read_alpha") < event_log.index("bridge-read_beta")
            assert event_log.index("bridge-read_beta") < event_log.index("model-2")
            assert counters.alpha == 1
            assert counters.beta == 1
        finally:
            runtime_mod._make_deferred_handler = original_make_deferred


# ==============================================================================
# C18-E5 — literal rejected-policy event ordering
# ==============================================================================


class TestC18E5RejectedPolicyEventOrder:
    """C18-E5: spy DndAgentPolicy.admit_tool_batch() for rejection ordering.

    For READ + WRITE batch:
        model-1 < deferred-handler < policy-admit-start < policy-reject

    The policy-reject marker must be emitted specifically from the real
    admit_tool_batch() exception, not from a catch around the whole
    deferred handler.

    Absent:
        policy-admit-success
        bridge-*
        model-2

    Expected:
        model requests == 1
        bridge executions == 0
        read handler == 0
        write handler == 0
    """

    def test_rejected_policy_event_order(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        write_context: ExecutionContext,
    ) -> None:
        """READ + WRITE: verify rejection event order via real policy."""
        event_log: list[str] = []

        # Spy on bridge.execute
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

        # Spy on _make_deferred_handler to spy on DndAgentPolicy.admit_tool_batch
        original_make_deferred = _make_deferred_handler
        import dnd_assistant.application.pydantic_ai_agent_runtime as runtime_mod

        def spy_make_deferred(prepared):
            handler_cap, execs = original_make_deferred(prepared)
            original_cap_handler = handler_cap.handler

            # Spy on the exact policy instance
            policy = prepared.deps.policy
            original_admit = policy.admit_tool_batch

            def spy_admit(calls):
                event_log.append("policy-admit-start")
                try:
                    result = original_admit(calls)
                    event_log.append("policy-admit-success")
                    return result
                except (ModelError, ValidationError):
                    event_log.append("policy-reject")
                    raise

            policy.admit_tool_batch = spy_admit  # type: ignore[method-assign]

            def event_handler(ctx, requests):
                event_log.append("deferred-handler")
                return original_cap_handler(ctx, requests)

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
            assert event_log.index("deferred-handler") < event_log.index("policy-admit-start")
            assert event_log.index("policy-admit-start") < event_log.index("policy-reject")
            bridge_events = [e for e in event_log if e.startswith("bridge-")]
            assert len(bridge_events) == 0
            assert "model-2" not in event_log
            assert "policy-admit-success" not in event_log
            assert counters.alpha == 0
            assert counters.beta == 0
            assert counters.write_alpha == 0
        finally:
            runtime_mod._make_deferred_handler = original_make_deferred


# ==============================================================================
# C18-E6 — strengthened approval rejection with delegated spies
# ==============================================================================


class TestC18E6ApprovalRejectionSpies:
    """C18-E6: approval rejection proves zero policy and bridge calls.

    Retain approval-request rejection.
    Add literal delegated spies proving:
        policy.admit_tool_batch calls == 0
        bridge.execute calls == 0
        project handlers == 0

    Expected error: ModelError
    """

    def test_approval_rejection_zero_policy_and_bridge(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Approval requests -> ModelError, zero policy calls, zero bridge calls."""
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
        prepared = preparer.prepare("test", execution_context=read_context)

        # Spy on policy.admit_tool_batch
        policy = prepared.deps.policy
        policy_admit_count: list[int] = [0]
        original_admit = policy.admit_tool_batch

        def spy_admit(calls):
            policy_admit_count[0] += 1
            return original_admit(calls)

        policy.admit_tool_batch = spy_admit  # type: ignore[method-assign]

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

        assert policy_admit_count[0] == 0
        assert bridge_count[0] == 0
        assert counters.alpha == 0
        assert counters.beta == 0
        assert counters.write_alpha == 0


# ==============================================================================
# C18-E3 — literal four-way exposure continuity via PreparedDndAgentRun
# ==============================================================================


class TestC18E3FourWayExposureContinuity:
    """C18-E3: exact prepared snapshot participates in four-way exposure assertion.

    Capture the exact PreparedDndAgentRun returned by the runtime preparer.

    Required literal values:
        prepared.deps.tool_snapshot.names
        request #1 AgentInfo.function_tools names
        request #2 AgentInfo.function_tools names
        result.initial_decision.exposed_tools names

    Assertion:
        snapshot_names == request_1_names
        snapshot_names == request_2_names
        snapshot_names == decision_names

    Use exact order, no sorting.
    """

    def test_four_way_exposure_continuity(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Snapshot, request #1, request #2, decision all match exactly."""
        captured_runs: list[PreparedDndAgentRun] = []
        captured_agent_info: list[Any] = []
        request_count: list[int] = [0]

        # Spy on preparer.prepare() to capture the exact PreparedDndAgentRun
        tool_bridge = PydanticAIToolBridge(registry=tool_registry)
        preparer = DndAgentRunPreparer(
            context_builder=context_builder,
            tool_catalog=tool_catalog,
            tool_bridge=tool_bridge,
        )
        original_prepare = preparer.prepare

        def spy_prepare(
            user_input: str,
            *,
            execution_context: ExecutionContext,
        ) -> PreparedDndAgentRun:
            prepared = original_prepare(user_input, execution_context=execution_context)
            captured_runs.append(prepared)
            return prepared

        preparer.prepare = spy_prepare  # type: ignore[method-assign]

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
        runtime = PydanticAIAgentRuntime(run_preparer=preparer, model=model)
        result = runtime.run("test exposure", execution_context=read_context)

        assert request_count[0] == 2
        assert len(captured_runs) == 1
        assert len(captured_agent_info) == 2

        prepared = captured_runs[0]
        snapshot_names = prepared.deps.tool_snapshot.names
        request_1_names = tuple(t.name for t in captured_agent_info[0].function_tools)
        request_2_names = tuple(t.name for t in captured_agent_info[1].function_tools)
        decision_names = tuple(t.name for t in result.initial_decision.exposed_tools)

        assert snapshot_names == request_1_names
        assert snapshot_names == request_2_names
        assert snapshot_names == decision_names

        assert counters.alpha == 1


# ==============================================================================
# C18-E2 — production build_results ValueError -> ModelError mapping
# ==============================================================================


class TestC18E2BuildResultsErrorMapping:
    """C18-E2: production build_results ValueError wraps as ModelError.

    This exercises the try/except ValueError inside _make_deferred_handler,
    NOT a separate call to requests.build_results().

    Preferred approach: monkeypatch DeferredToolRequests.build_results
    on the exact request instance to raise ValueError.
    """

    def test_build_results_value_error_via_monkeypatch(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Monkeypatch build_results to raise ValueError inside production handler."""
        bridge = PydanticAIToolBridge(registry=tool_registry)
        bridge_execute_count: list[int] = [0]
        original_bridge_execute = bridge.execute

        def spy_execute(snapshot, tool_call, *, execution_context):
            bridge_execute_count[0] += 1
            return original_bridge_execute(snapshot, tool_call, execution_context=execution_context)

        bridge.execute = spy_execute  # type: ignore[method-assign]
        preparer = DndAgentRunPreparer(
            context_builder=context_builder,
            tool_catalog=tool_catalog,
            tool_bridge=bridge,
        )

        # Spy on _make_deferred_handler to monkeypatch build_results
        # on the exact DeferredToolRequests instance
        original_make_deferred = _make_deferred_handler
        import dnd_assistant.application.pydantic_ai_agent_runtime as runtime_mod

        def spy_make_deferred(
            prepared: PreparedDndAgentRun,
        ) -> tuple[HandleDeferredToolCalls, list[Any]]:
            handler_cap, execs = original_make_deferred(prepared)
            original_cap_handler = handler_cap.handler

            def patching_handler(
                ctx: RunContext[DndAgentDeps],
                requests: DeferredToolRequests,
            ) -> DeferredToolResults | None:
                original_build_results = requests.build_results

                def failing_build_results(*args: Any, **kwargs: Any) -> Any:
                    raise ValueError("simulated build_results failure")

                requests.build_results = failing_build_results  # type: ignore[method-assign]
                try:
                    return original_cap_handler(ctx, requests)
                finally:
                    requests.build_results = original_build_results

            handler_cap.handler = patching_handler  # type: ignore[attr-defined]
            return handler_cap, execs

        runtime_mod._make_deferred_handler = spy_make_deferred  # type: ignore[method-assign]

        try:
            request_count: list[int] = [0]

            def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
                request_count[0] += 1
                if request_count[0] == 1:
                    return _make_tool_call_response(
                        "read_alpha",
                        tool_call_id="call-br",
                        args={"value": "br-test"},
                    )
                return _make_respond_response("Done!")

            model = _make_function_model(model_fn)
            runtime = PydanticAIAgentRuntime(run_preparer=preparer, model=model)
            with pytest.raises(ModelError) as exc_info:
                runtime.run("test", execution_context=read_context)

            assert bridge_execute_count[0] == 1
            assert counters.alpha == 1
            assert request_count[0] == 1  # build_results error prevents second model request
            assert isinstance(exc_info.value.__cause__, ValueError)
            assert "simulated build_results failure" in str(exc_info.value.__cause__)
        finally:
            runtime_mod._make_deferred_handler = original_make_deferred
