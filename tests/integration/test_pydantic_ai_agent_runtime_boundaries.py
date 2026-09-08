"""PAIM-08: Pydantic AI bounded agent runtime — boundary/safety tests.

All tests use ``FunctionModel`` for deterministic model responses and require
no real Ollama or network access.
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

from dnd_assistant.application.agent_context import (
    AgentContextBuilder,
)
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
                args=args or {"x": 42},
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


# ==============================================================================
# Fixtures
# ==============================================================================


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
        session_repository=_StubSessionRepo(),  # type: ignore[arg-type]
        event_repository=_StubEventRepo(),  # type: ignore[arg-type]
        world_time_repository=_StubWorldTimeRepo(),  # type: ignore[arg-type]
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
# P8-13: 5 calls rejected pre-execution
# ==============================================================================


class TestP813FiveCallsRejected:
    """P8-13: Five tool calls rejected before any execution."""

    def test_five_calls_rejected(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Model requests 5 tools — ModelError before any execution."""
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            return ModelResponse(
                parts=[
                    ToolCallPart(tool_name="read_alpha", args={"value": "a"}, tool_call_id="c1"),
                    ToolCallPart(tool_name="read_beta", args={"number": 1}, tool_call_id="c2"),
                    ToolCallPart(tool_name="read_alpha", args={"value": "b"}, tool_call_id="c3"),
                    ToolCallPart(tool_name="read_beta", args={"number": 2}, tool_call_id="c4"),
                    ToolCallPart(tool_name="read_alpha", args={"value": "c"}, tool_call_id="c5"),
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
# P8-14: READ+WRITE rejected pre-execution
# ==============================================================================


class TestP814ReadWriteRejected:
    """P8-14: Mixed READ+WRITE batch rejected before any execution."""

    def test_read_write_rejected(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Model requests READ+WRITE — ModelError before any execution."""
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            return ModelResponse(
                parts=[
                    ToolCallPart(tool_name="read_alpha", args={"value": "a"}, tool_call_id="c1"),
                    ToolCallPart(tool_name="write_alpha", args={"value": "b"}, tool_call_id="c2"),
                ]
            )

        model = _make_function_model(model_fn)
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        with pytest.raises(ModelError):
            runtime.run("test", execution_context=read_context)

        assert request_count[0] == 1
        assert counters.alpha == 0
        assert counters.write_alpha == 0


# ==============================================================================
# P8-15: WRITE+WRITE rejected pre-execution
# ==============================================================================


class TestP815WriteWriteRejected:
    """P8-15: Multiple WRITE batch rejected before any execution."""

    def test_write_write_rejected(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        write_context: ExecutionContext,
    ) -> None:
        """Model requests WRITE+WRITE — ModelError before any execution."""
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
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        with pytest.raises(ModelError):
            runtime.run("test", execution_context=write_context)

        assert request_count[0] == 1
        assert counters.write_alpha == 0


# ==============================================================================
# P8-16: Duplicate ID rejected pre-execution
# ==============================================================================


class TestP816DuplicateIdRejected:
    """P8-16: Duplicate tool_call_id rejected before handler/execution."""

    def test_duplicate_id_rejected(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Model sends two calls with same ID — ModelError before execution."""
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            return ModelResponse(
                parts=[
                    ToolCallPart(tool_name="read_alpha", args={"value": "a"}, tool_call_id="dup"),
                    ToolCallPart(tool_name="read_beta", args={"number": 1}, tool_call_id="dup"),
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
# P8-17: Unknown tool rejected pre-execution
# ==============================================================================


class TestP817UnknownToolRejected:
    """P8-17: Unknown tool name rejected before execution."""

    def test_unknown_tool_rejected(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Model requests an unregistered tool — ModelError before execution."""
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            return _make_tool_call_response(
                "unknown_tool",
                tool_call_id="c1",
                args={"x": 1},
            )

        model = _make_function_model(model_fn)
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        with pytest.raises(ModelError):
            runtime.run("test", execution_context=read_context)

        assert request_count[0] == 1
        assert counters.alpha == 0


# ==============================================================================
# P8-18: Hidden tool rejected pre-execution
# ==============================================================================


class TestP818HiddenToolRejected:
    """P8-18: Hidden (live-registry but not exposed) tool rejected."""

    def test_hidden_tool_rejected(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Model requests a registered but unexposed tool — ModelError."""
        request_count: list[int] = [0]

        # write_alpha is registered but not exposed in READ context
        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            return _make_tool_call_response(
                "write_alpha",
                tool_call_id="c1",
                args={"value": "hidden"},
            )

        model = _make_function_model(model_fn)
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        with pytest.raises(ModelError):
            runtime.run("test", execution_context=read_context)

        assert request_count[0] == 1
        assert counters.write_alpha == 0


# ==============================================================================
# P8-19: Invalid tool schema → ToolExecutor ValidationError
# ==============================================================================


class TestP819InvalidSchema:
    """P8-19: Schema-invalid tool arguments reach ToolExecutor and fail."""

    def test_invalid_schema(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Model sends invalid args — ValidationError from ToolExecutor."""
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            return _make_tool_call_response(
                "read_alpha",
                tool_call_id="c1",
                args={"value": 123},
            )

        model = _make_function_model(model_fn)
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        with pytest.raises(ValidationError):
            runtime.run("test", execution_context=read_context)

        assert request_count[0] == 1
        assert counters.alpha == 0


# ==============================================================================
# P8-20: Sequential fail-fast
# ==============================================================================


class TestP820SequentialFailFast:
    """P8-20: Sequential fail-fast — second call fails, third never executes."""

    def test_sequential_fail_fast(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Three READ calls — second fails, third never executes."""
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            return ModelResponse(
                parts=[
                    ToolCallPart(tool_name="read_alpha", args={"value": "ok"}, tool_call_id="c1"),
                    ToolCallPart(tool_name="read_alpha", args={"value": 123}, tool_call_id="c2"),
                    ToolCallPart(tool_name="read_beta", args={"number": 42}, tool_call_id="c3"),
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
# P8-21: Second deferred batch rejected
# ==============================================================================


class TestP821SecondDeferredBatch:
    """P8-21: Second deferred batch rejected before additional execution."""

    def test_second_deferred_batch_rejected(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Model requests tools again after first batch — ModelError."""
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="read_alpha", args={"value": "a"}, tool_call_id="c1"
                        ),
                    ]
                )
            return ModelResponse(
                parts=[
                    ToolCallPart(tool_name="read_beta", args={"number": 1}, tool_call_id="c2"),
                ]
            )

        model = _make_function_model(model_fn)
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        with pytest.raises(ModelError):
            runtime.run("test", execution_context=read_context)

        assert request_count[0] == 2
        assert counters.alpha == 1
        assert counters.beta == 0


# ==============================================================================
# P8-22: Malformed direct terminal outcome
# ==============================================================================


class TestP822MalformedDirectOutcome:
    """P8-22: Malformed direct terminal outcome → ModelError."""

    def test_malformed_direct_outcome(
        self,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Model returns malformed JSON — ModelError, 1 request, 0 tools."""
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            return ModelResponse(parts=[TextPart(content="not valid json {{{")])

        model = _make_function_model(model_fn)
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        with pytest.raises(ModelError):
            runtime.run("test", execution_context=read_context)

        assert request_count[0] == 1


# ==============================================================================
# P8-23: Malformed post-tool terminal outcome
# ==============================================================================


class TestP823MalformedPostToolOutcome:
    """P8-23: Malformed post-tool terminal outcome → ModelError."""

    def test_malformed_post_tool_outcome(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Model returns malformed JSON after tool — ModelError, 2 requests."""
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return _make_tool_call_response(
                    "read_alpha",
                    tool_call_id="c1",
                    args={"value": "hello"},
                )
            return ModelResponse(parts=[TextPart(content="bad json {{{")])

        model = _make_function_model(model_fn)
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        with pytest.raises(ModelError):
            runtime.run("test", execution_context=read_context)

        assert request_count[0] == 2
        assert counters.alpha == 1


# ==============================================================================
# P8-24: First-response text + tool preserved
# ==============================================================================


class TestP824FirstResponseTextAndTool:
    """P8-24: First response with text + tool call is preserved."""

    def test_first_response_text_and_tool(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Model returns text + tool call — both preserved in initial_decision."""
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return ModelResponse(
                    parts=[
                        TextPart(content="Looking up..."),
                        ToolCallPart(
                            tool_name="read_alpha",
                            args={"value": "preserve"},
                            tool_call_id="c1",
                        ),
                    ]
                )
            return _make_respond_response("Done!")

        model = _make_function_model(model_fn)
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        result = runtime.run("test", execution_context=read_context)

        assert request_count[0] == 2
        assert result.initial_decision.response.message.content == "Looking up..."
        assert len(result.initial_decision.response.message.tool_calls) == 1
        assert result.initial_decision.response.message.tool_calls[0].name == "read_alpha"
        assert len(result.tool_executions) == 1


# ==============================================================================
# P8-25: ThinkingPart hidden
# ==============================================================================


class TestP825ThinkingPartHidden:
    """P8-25: ThinkingPart content must not become assistant content."""

    def test_thinking_part_hidden(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Model returns ThinkingPart — only TextPart content is surfaced."""
        from pydantic_ai.messages import ThinkingPart

        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return ModelResponse(
                    parts=[
                        ThinkingPart(content="hidden thought"),
                        ToolCallPart(
                            tool_name="read_alpha",
                            args={"value": "think"},
                            tool_call_id="c1",
                        ),
                    ]
                )
            return _make_respond_response("Done!")

        model = _make_function_model(model_fn)
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        result = runtime.run("test", execution_context=read_context)

        assert request_count[0] == 2
        assert result.initial_decision.response.message.content is None
        assert len(result.tool_executions) == 1


# ==============================================================================
# P8-26: Omitted tool IDs handled
# ==============================================================================


class TestP826OmittedToolIds:
    """P8-26: Omitted tool IDs are handled by framework."""

    def test_omitted_tool_ids(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Two calls without explicit IDs — framework assigns unique IDs."""
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(tool_name="read_alpha", args={"value": "a"}),
                        ToolCallPart(tool_name="read_beta", args={"number": 1}),
                    ]
                )
            return _make_respond_response("Done!")

        model = _make_function_model(model_fn)
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        result = runtime.run("test", execution_context=read_context)

        assert request_count[0] == 2
        assert len(result.tool_executions) == 2
        assert result.tool_executions[0].tool_call.call_id is not None
        assert result.tool_executions[1].tool_call.call_id is not None
        assert (
            result.tool_executions[0].tool_call.call_id
            != result.tool_executions[1].tool_call.call_id
        )


# ==============================================================================
# P8-27: Explicit single None ID
# ==============================================================================


class TestP827ExplicitNoneId:
    """P8-27: Explicit single None tool_call_id behavior."""

    def test_explicit_none_id(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Single call with explicit None ID — framework may resolve inline."""
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="read_alpha",
                            args={"value": "none-id"},
                            tool_call_id=None,
                        ),
                    ]
                )
            return _make_respond_response("Done!")

        model = _make_function_model(model_fn)
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        result = runtime.run("test", execution_context=read_context)

        assert request_count[0] == 2
        assert len(result.tool_executions) == 1
        assert counters.alpha == 1


# ==============================================================================
# P8-28: Import boundary — fresh process
# ==============================================================================


class TestP828ImportBoundary:
    """P8-28: Fresh-process import boundary for pydantic_ai_agent_runtime."""

    def test_fresh_import_does_not_load_forbidden_modules(self) -> None:
        """A fresh import must not eagerly load storage/retrieval/cli/executor."""
        import subprocess
        import sys

        code = """
import sys
import dnd_assistant.application.pydantic_ai_agent_runtime

forbidden = [
    'dnd_assistant.models.gateway',
    'dnd_assistant.models.ollama',
    'dnd_assistant.storage',
    'dnd_assistant.retrieval',
    'dnd_assistant.cli',
    'dnd_assistant.tools.executor',
]
loaded = [m for m in forbidden if m in sys.modules]
if loaded:
    print('FAIL:' + ','.join(loaded))
    sys.exit(1)

print('PASS')
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, (
            f"Import isolation failed: stdout={result.stdout}, stderr={result.stderr}"
        )
        assert "PASS" in result.stdout
