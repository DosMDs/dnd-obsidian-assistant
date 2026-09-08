"""PAIM-C15: Seal PAIM-08 structural preflight and runtime evidence.

This file provides executable evidence for the PAIM-C15 correction.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models import Model
from pydantic_ai.models.function import FunctionModel

from dnd_assistant.application.agent_context import AgentContextBuilder
from dnd_assistant.application.pydantic_ai_agent_runtime import (
    PydanticAIAgentRuntime,
)
from dnd_assistant.application.pydantic_ai_run_deps import (
    DndAgentRunPreparer,
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
# C15-S1 — structurally invalid/non-finite batch
# ==============================================================================


class TestC15S1StructuralInvalidBatch:
    """C15-S1: structurally invalid/non-finite batch — zero executions."""

    def test_single_non_finite_raises_model_error(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Single call with NaN value — ModelError, zero bridge executions."""
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            return _make_tool_call_response(
                "read_alpha",
                tool_call_id="call-1",
                args={"value": float("nan")},
            )

        model = _make_function_model(model_fn)
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        with pytest.raises(ModelError):
            runtime.run("test", execution_context=read_context)

        assert request_count[0] == 1
        assert counters.alpha == 0
        assert counters.beta == 0

    def test_valid_non_finite_valid_batch(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Batch: valid + NaN + valid — ModelError, zero bridge executions."""
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
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
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        with pytest.raises(ModelError):
            runtime.run("test", execution_context=read_context)

        assert request_count[0] == 1
        assert counters.alpha == 0
        assert counters.beta == 0


# ==============================================================================
# C15-S2 — tool-schema fail-fast (sequential)
# ==============================================================================


class TestC15S2SchemaFailFast:
    """C15-S2: tool-schema fail-fast — second call fails, third never executes."""

    def test_schema_fail_fast(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Call 1 valid, call 2 schema-invalid, call 3 never reaches bridge."""
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            return ModelResponse(
                parts=[
                    ToolCallPart(tool_name="read_alpha", args={"value": "ok"}, tool_call_id="c1"),
                    ToolCallPart(tool_name="read_alpha", args={"value": 123}, tool_call_id="c2"),
                    ToolCallPart(tool_name="read_beta", args={"value": "never"}, tool_call_id="c3"),
                ]
            )

        model = _make_function_model(model_fn)
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        with pytest.raises(ValidationError):
            runtime.run("test", execution_context=read_context)

        assert request_count[0] == 1
        assert counters.alpha == 1
        assert counters.beta == 0


# ==============================================================================
# C15-S3 — runtime deps binding
# ==============================================================================


class TestC15S3RuntimeDepsBinding:
    """C15-S3: deferred handler validates ctx.deps is prepared.deps."""

    def test_ctx_deps_is_prepared_deps(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Deferred handler receives ctx.deps that is prepared.deps."""
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return _make_tool_call_response(
                    "read_alpha",
                    tool_call_id="call-1",
                    args={"value": "deps-test"},
                )
            return _make_respond_response("Done!")

        model = _make_function_model(model_fn)
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        result = runtime.run("test", execution_context=read_context)

        assert request_count[0] == 2
        assert len(result.tool_executions) == 1
        assert counters.alpha == 1


# ==============================================================================
# C15-S4 — same-run evidence
# ==============================================================================


class TestC15S4SameRunEvidence:
    """C15-S4: one Agent.run_sync, two model requests."""

    def test_same_run_two_requests(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """One Agent.run_sync invocation, two FunctionModel requests."""
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
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

        assert request_count[0] == 2
        assert len(result.tool_executions) == 1


# ==============================================================================
# C15-S5 — tool-execution result evidence
# ==============================================================================


class TestC15S5BridgeExecutionCounts:
    """C15-S5: literal bridge execution counts."""

    def test_single_read_one_bridge_exec(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Single READ -> 1 bridge execution, 1 handler."""
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
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        result = runtime.run("test", execution_context=read_context)

        assert request_count[0] == 2
        assert len(result.tool_executions) == 1
        assert counters.alpha == 1

    def test_two_read_two_bridge_execs(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """2 READ -> 2 bridge executions, 2 handlers."""
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="read_alpha", args={"value": "a"}, tool_call_id="c1"
                        ),
                        ToolCallPart(tool_name="read_beta", args={"number": 42}, tool_call_id="c2"),
                    ]
                )
            return _make_respond_response("Both done!")

        model = _make_function_model(model_fn)
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        result = runtime.run("test", execution_context=read_context)

        assert request_count[0] == 2
        assert len(result.tool_executions) == 2
        assert counters.alpha == 1
        assert counters.beta == 1


# ==============================================================================
# C15-S6 — no-tool-call respond
# ==============================================================================


class TestC15S6NoToolCallRespond:
    """C15-S6: model responds without tool calls — zero executions."""

    def test_no_tool_call_respond(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Model returns text response with no tool calls."""
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            return _make_respond_response("No tools needed!")

        model = _make_function_model(model_fn)
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        result = runtime.run("test", execution_context=read_context)

        assert request_count[0] == 1
        assert len(result.tool_executions) == 0


# ==============================================================================
# C15-S7 — write-permission batch (audit required)
# ==============================================================================


class TestC15S7SingleWriteExecution:
    """C15-S7: single WRITE tool execution through bridge."""

    def test_single_write_execution(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        write_context: ExecutionContext,
    ) -> None:
        """Single WRITE call executes through bridge."""
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
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        result = runtime.run("test", execution_context=write_context)

        assert request_count[0] == 2
        assert len(result.tool_executions) == 1
        assert result.tool_executions[0].tool_call.name == "write_alpha"
        assert counters.write_alpha == 1


# ==============================================================================
# C15-S8 — mixed read/write batch (forbidden)
# ==============================================================================


class TestC15S8MixedReadWriteBatch:
    """C15-S8: mixed read/write batch — forbidden before first execution."""

    def test_mixed_batch_rejected(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        write_context: ExecutionContext,
    ) -> None:
        """Mixed READ + WRITE in same batch — rejected, zero bridge executions."""
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

        assert request_count[0] == 1
        assert counters.alpha == 0
        assert counters.write_alpha == 0


# ==============================================================================
# C15-S9 — duplicate call-id fail-close
# ==============================================================================


class TestC15S9DuplicateCallId:
    """C15-S9: duplicate tool_call_id — fail-close, zero bridge executions."""

    def test_duplicate_call_id_rejected(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Two calls with same tool_call_id — rejected, zero bridge executions."""
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            return ModelResponse(
                parts=[
                    ToolCallPart(
                        tool_name="read_alpha",
                        args={"value": "first"},
                        tool_call_id="dup-id",
                    ),
                    ToolCallPart(
                        tool_name="read_beta",
                        args={"value": "second"},
                        tool_call_id="dup-id",
                    ),
                ]
            )

        model = _make_function_model(model_fn)
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        with pytest.raises(ModelError):
            runtime.run("test", execution_context=read_context)

        assert request_count[0] == 1
        assert counters.alpha == 0
        assert counters.beta == 0
