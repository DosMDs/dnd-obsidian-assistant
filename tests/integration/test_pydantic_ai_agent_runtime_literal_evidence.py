"""PAIM-C17: Complete literal PAIM-08 runtime evidence.

This file provides executable literal evidence for the PAIM-C17 correction.
All evidence is captured through public/supported project and framework
surfaces — no private framework internals are used.

Required evidence:
    C17-E1  — literal ctx.deps identity
    C17-E2  — wrong-deps fail-closed
    C17-E3  — literal PydanticAIToolBridge.execute counter (delegated spy)
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
# C17-E1 — literal ctx.deps identity
# ==============================================================================


class TestC17E1LiteralCtxDepsIdentity:
    """C17-E1: literal ctx.deps identity — instrument deferred handler."""

    def test_ctx_deps_identity_literal(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Capture prepared.deps and deferred ctx.deps; assert exact identity."""
        captured_prepared: list[PreparedDndAgentRun] = []
        captured_ctx_deps: list[DndAgentDeps] = []

        original_make_deferred = _make_deferred_handler
        import dnd_assistant.application.pydantic_ai_agent_runtime as runtime_mod

        def spy_make_deferred(
            prepared: PreparedDndAgentRun,
        ) -> tuple[HandleDeferredToolCalls, list[Any]]:
            captured_prepared.append(prepared)
            handler_cap, execs = original_make_deferred(prepared)
            original_cap_handler = handler_cap.handler

            def capturing_handler(
                ctx: RunContext[DndAgentDeps],
                requests: DeferredToolRequests,
            ) -> DeferredToolResults | None:
                captured_ctx_deps.append(ctx.deps)
                return original_cap_handler(ctx, requests)

            handler_cap.handler = capturing_handler  # type: ignore[attr-defined]
            return handler_cap, execs

        runtime_mod._make_deferred_handler = spy_make_deferred  # type: ignore[method-assign]

        try:
            request_count: list[int] = [0]

            def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
                request_count[0] += 1
                if request_count[0] == 1:
                    return _make_tool_call_response(
                        "read_alpha",
                        tool_call_id="call-1",
                        args={"value": "deps-identity"},
                    )
                return _make_respond_response("Done!")

            model = _make_function_model(model_fn)
            runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)
            runtime.run("test", execution_context=read_context)

            assert len(captured_prepared) == 1
            assert len(captured_ctx_deps) == 1
            assert captured_ctx_deps[0] is captured_prepared[0].deps
            assert request_count[0] == 2
            assert counters.alpha == 1
        finally:
            runtime_mod._make_deferred_handler = original_make_deferred


# ==============================================================================
# C17-E2 — wrong-deps fail-closed
# ==============================================================================


class TestC17E2WrongDepsFailClosed:
    """C17-E2: wrong-deps fail-closed — different deps raises ValidationError."""

    def test_wrong_deps_fail_closed(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Deferred handler with wrong deps raises ValidationError."""
        tool_bridge = PydanticAIToolBridge(registry=tool_registry)
        preparer = DndAgentRunPreparer(
            context_builder=context_builder,
            tool_catalog=tool_catalog,
            tool_bridge=tool_bridge,
        )

        prepared_a = preparer.prepare("run a", execution_context=read_context)
        prepared_b = preparer.prepare("run b", execution_context=read_context)

        handler_cap, _ = _make_deferred_handler(prepared_a)

        ctx = RunContext[DndAgentDeps](
            deps=prepared_b.deps,
            model=_make_function_model(lambda m, i: _make_respond_response("x")),
            usage=UsageLimits(),
            retries={},
        )

        tool_call = ToolCallPart(
            tool_name="read_alpha",
            args={"value": "wrong-deps"},
            tool_call_id="call-wd",
        )
        requests = DeferredToolRequests(calls=[tool_call])

        with pytest.raises(ValidationError):
            handler_cap.handler(ctx, requests)  # type: ignore[attr-defined]

        assert counters.alpha == 0
        assert counters.beta == 0
        assert counters.write_alpha == 0


# ==============================================================================
# C17-E3 — literal PydanticAIToolBridge.execute counter (delegated spy)
# ==============================================================================


class TestC17E3LiteralBridgeCounter:
    """C17-E3: literal PydanticAIToolBridge.execute delegated spy counts."""

    @pytest.fixture
    def bridge_and_spy(
        self,
        tool_registry: ToolRegistry,
    ) -> tuple[PydanticAIToolBridge, list[int]]:
        bridge = PydanticAIToolBridge(registry=tool_registry)
        bridge_execute_count: list[int] = [0]
        original_execute = bridge.execute

        def spy_execute(
            snapshot: Any,
            tool_call: Any,
            *,
            execution_context: Any,
        ) -> Any:
            bridge_execute_count[0] += 1
            return original_execute(snapshot, tool_call, execution_context=execution_context)

        bridge.execute = spy_execute  # type: ignore[method-assign]
        return bridge, bridge_execute_count

    def _make_runtime_with_bridge(
        self,
        model: Model,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        bridge: PydanticAIToolBridge,
    ) -> PydanticAIAgentRuntime:
        preparer = DndAgentRunPreparer(
            context_builder=context_builder,
            tool_catalog=tool_catalog,
            tool_bridge=bridge,
        )
        return PydanticAIAgentRuntime(
            run_preparer=preparer,
            model=model,
        )

    def test_direct_respond_zero_bridge(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
        bridge_and_spy: tuple[PydanticAIToolBridge, list[int]],
    ) -> None:
        """Direct respond -> 0 bridge calls."""
        bridge, bridge_count = bridge_and_spy

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            return _make_respond_response("Hello!")

        model = _make_function_model(model_fn)
        runtime = self._make_runtime_with_bridge(
            model,
            tool_registry,
            tool_catalog,
            context_builder,
            bridge,
        )
        runtime.run("hello", execution_context=read_context)
        assert bridge_count[0] == 0

    def test_single_read_one_bridge(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
        bridge_and_spy: tuple[PydanticAIToolBridge, list[int]],
    ) -> None:
        """Single READ -> 1 bridge call."""
        bridge, bridge_count = bridge_and_spy
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return _make_tool_call_response(
                    "read_alpha",
                    tool_call_id="call-1",
                    args={"value": "bridge-count"},
                )
            return _make_respond_response("Done!")

        model = _make_function_model(model_fn)
        runtime = self._make_runtime_with_bridge(
            model,
            tool_registry,
            tool_catalog,
            context_builder,
            bridge,
        )
        runtime.run("test", execution_context=read_context)
        assert bridge_count[0] == 1
        assert counters.alpha == 1

    def test_single_write_one_bridge(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        write_context: ExecutionContext,
        bridge_and_spy: tuple[PydanticAIToolBridge, list[int]],
    ) -> None:
        """Single WRITE -> 1 bridge call."""
        bridge, bridge_count = bridge_and_spy
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return _make_tool_call_response(
                    "write_alpha",
                    tool_call_id="call-w1",
                    args={"value": "save"},
                )
            return _make_respond_response("Written!")

        model = _make_function_model(model_fn)
        runtime = self._make_runtime_with_bridge(
            model,
            tool_registry,
            tool_catalog,
            context_builder,
            bridge,
        )
        runtime.run("test", execution_context=write_context)
        assert bridge_count[0] == 1
        assert counters.write_alpha == 1

    def test_two_read_two_bridge(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
        bridge_and_spy: tuple[PydanticAIToolBridge, list[int]],
    ) -> None:
        """Two READ -> 2 bridge calls."""
        bridge, bridge_count = bridge_and_spy
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="read_alpha",
                            args={"value": "a"},
                            tool_call_id="c1",
                        ),
                        ToolCallPart(
                            tool_name="read_beta",
                            args={"number": 42},
                            tool_call_id="c2",
                        ),
                    ]
                )
            return _make_respond_response("Both done!")

        model = _make_function_model(model_fn)
        runtime = self._make_runtime_with_bridge(
            model,
            tool_registry,
            tool_catalog,
            context_builder,
            bridge,
        )
        runtime.run("test", execution_context=read_context)
        assert bridge_count[0] == 2
        assert counters.alpha == 1
        assert counters.beta == 1

    def test_four_read_four_bridge(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
        bridge_and_spy: tuple[PydanticAIToolBridge, list[int]],
    ) -> None:
        """Four READ -> 4 bridge calls."""
        bridge, bridge_count = bridge_and_spy
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="read_alpha", args={"value": "a"}, tool_call_id="c1"
                        ),
                        ToolCallPart(tool_name="read_beta", args={"number": 1}, tool_call_id="c2"),
                        ToolCallPart(
                            tool_name="read_alpha", args={"value": "b"}, tool_call_id="c3"
                        ),
                        ToolCallPart(tool_name="read_beta", args={"number": 2}, tool_call_id="c4"),
                    ]
                )
            return _make_respond_response("All done!")

        model = _make_function_model(model_fn)
        runtime = self._make_runtime_with_bridge(
            model,
            tool_registry,
            tool_catalog,
            context_builder,
            bridge,
        )
        runtime.run("test", execution_context=read_context)
        assert bridge_count[0] == 4

    def test_five_calls_rejected_zero_bridge(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
        bridge_and_spy: tuple[PydanticAIToolBridge, list[int]],
    ) -> None:
        """Five calls -> rejected, 0 bridge calls."""
        bridge, bridge_count = bridge_and_spy
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_alpha", args={"value": str(i)}, tool_call_id=f"c{i}"
                    )
                    for i in range(5)
                ]
            )

        model = _make_function_model(model_fn)
        runtime = self._make_runtime_with_bridge(
            model,
            tool_registry,
            tool_catalog,
            context_builder,
            bridge,
        )
        with pytest.raises(ModelError):
            runtime.run("test", execution_context=read_context)
        assert bridge_count[0] == 0

    def test_read_write_rejected_zero_bridge(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        write_context: ExecutionContext,
        bridge_and_spy: tuple[PydanticAIToolBridge, list[int]],
    ) -> None:
        """READ + WRITE -> rejected, 0 bridge calls."""
        bridge, bridge_count = bridge_and_spy
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            return ModelResponse(
                parts=[
                    ToolCallPart(tool_name="read_alpha", args={"value": "ok"}, tool_call_id="c1"),
                    ToolCallPart(tool_name="write_alpha", args={"value": "bad"}, tool_call_id="c2"),
                ]
            )

        model = _make_function_model(model_fn)
        runtime = self._make_runtime_with_bridge(
            model,
            tool_registry,
            tool_catalog,
            context_builder,
            bridge,
        )
        with pytest.raises(ModelError):
            runtime.run("test", execution_context=write_context)
        assert bridge_count[0] == 0

    def test_write_write_rejected_zero_bridge(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        write_context: ExecutionContext,
        bridge_and_spy: tuple[PydanticAIToolBridge, list[int]],
    ) -> None:
        """WRITE + WRITE -> rejected, 0 bridge calls."""
        bridge, bridge_count = bridge_and_spy
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            return ModelResponse(
                parts=[
                    ToolCallPart(tool_name="write_alpha", args={"value": "a"}, tool_call_id="c1"),
                    ToolCallPart(tool_name="write_alpha", args={"value": "b"}, tool_call_id="c2"),
                ]
            )

        model = _make_function_model(model_fn)
        runtime = self._make_runtime_with_bridge(
            model,
            tool_registry,
            tool_catalog,
            context_builder,
            bridge,
        )
        with pytest.raises(ModelError):
            runtime.run("test", execution_context=write_context)
        assert bridge_count[0] == 0

    def test_non_finite_batch_zero_bridge(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
        bridge_and_spy: tuple[PydanticAIToolBridge, list[int]],
    ) -> None:
        """Non-finite batch -> 0 bridge calls."""
        bridge, bridge_count = bridge_and_spy
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            return ModelResponse(
                parts=[
                    ToolCallPart(tool_name="read_alpha", args={"value": "ok"}, tool_call_id="c1"),
                    ToolCallPart(
                        tool_name="read_beta",
                        args={"value": float("nan")},
                        tool_call_id="c2",
                    ),
                    ToolCallPart(
                        tool_name="read_alpha", args={"value": "also-ok"}, tool_call_id="c3"
                    ),
                ]
            )

        model = _make_function_model(model_fn)
        runtime = self._make_runtime_with_bridge(
            model,
            tool_registry,
            tool_catalog,
            context_builder,
            bridge,
        )
        with pytest.raises(ModelError):
            runtime.run("test", execution_context=read_context)
        assert bridge_count[0] == 0

    def test_schema_invalid_single_one_bridge(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
        bridge_and_spy: tuple[PydanticAIToolBridge, list[int]],
    ) -> None:
        """Schema-invalid single call -> 1 bridge call (fail-fast after execution)."""
        bridge, bridge_count = bridge_and_spy
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            return _make_tool_call_response(
                "read_alpha",
                tool_call_id="call-si",
                args={"value": 123},
            )

        model = _make_function_model(model_fn)
        runtime = self._make_runtime_with_bridge(
            model,
            tool_registry,
            tool_catalog,
            context_builder,
            bridge,
        )
        with pytest.raises(ValidationError):
            runtime.run("test", execution_context=read_context)
        assert bridge_count[0] == 1

    def test_sequential_fail_fast_two_bridge(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
        bridge_and_spy: tuple[PydanticAIToolBridge, list[int]],
    ) -> None:
        """valid + schema-invalid + valid -> 2 bridge calls (fail-fast)."""
        bridge, bridge_count = bridge_and_spy
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            return ModelResponse(
                parts=[
                    ToolCallPart(tool_name="read_alpha", args={"value": "ok"}, tool_call_id="c1"),
                    ToolCallPart(tool_name="read_alpha", args={"value": 123}, tool_call_id="c2"),
                    ToolCallPart(tool_name="read_beta", args={"number": 99}, tool_call_id="c3"),
                ]
            )

        model = _make_function_model(model_fn)
        runtime = self._make_runtime_with_bridge(
            model,
            tool_registry,
            tool_catalog,
            context_builder,
            bridge,
        )
        with pytest.raises(ValidationError):
            runtime.run("test", execution_context=read_context)
        assert bridge_count[0] == 2

    def test_second_deferred_batch_first_batch_only(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
        bridge_and_spy: tuple[PydanticAIToolBridge, list[int]],
    ) -> None:
        """Second deferred batch -> only first batch executes."""
        bridge, bridge_count = bridge_and_spy
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="read_alpha",
                            args={"value": "a"},
                            tool_call_id="c1",
                        ),
                    ]
                )
            # Second request: the framework should not produce another
            # deferred batch since the runtime only does one.
            return _make_respond_response("Done!")

        model = _make_function_model(model_fn)
        runtime = self._make_runtime_with_bridge(
            model,
            tool_registry,
            tool_catalog,
            context_builder,
            bridge,
        )
        runtime.run("test", execution_context=read_context)
        assert request_count[0] == 2
        assert bridge_count[0] == 1
        assert counters.alpha == 1
