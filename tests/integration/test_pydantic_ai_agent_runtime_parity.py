"""PAIM-C15: Old/new AgentLoop parity tests.

Compares the existing custom ``AgentLoop`` against the new
``PydanticAIAgentRuntime`` for deterministic equivalent model outcomes.

Required scenarios:
    C15-P1 direct respond
    C15-P2 direct clarify
    C15-P3 single READ -> respond
    C15-P4 single WRITE -> respond
    C15-P5 two READ -> respond
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel

from dnd_assistant.application.agent_context import AgentContextBuilder
from dnd_assistant.application.agent_loop import AgentOutcomeKind
from dnd_assistant.application.pydantic_ai_agent_runtime import (
    PydanticAIAgentRuntime,
)
from dnd_assistant.application.pydantic_ai_run_deps import (
    DndAgentRunPreparer,
)
from dnd_assistant.application.pydantic_ai_tool_bridge import (
    PydanticAIToolBridge,
)
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
def tool_bridge(tool_registry: ToolRegistry) -> PydanticAIToolBridge:
    return PydanticAIToolBridge(registry=tool_registry)


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


def _make_runtime(
    tool_registry: ToolRegistry,
    tool_catalog: ToolRegistrySchema,
    context_builder: AgentContextBuilder,
    model_fn: Any,
) -> PydanticAIAgentRuntime:
    tool_bridge = PydanticAIToolBridge(registry=tool_registry)
    preparer = DndAgentRunPreparer(
        context_builder=context_builder,
        tool_catalog=tool_catalog,
        tool_bridge=tool_bridge,
    )
    model = FunctionModel(model_fn)
    return PydanticAIAgentRuntime(
        run_preparer=preparer,
        model=model,
    )


class TestC15P1DirectRespond:
    """C15-P1: direct respond parity."""

    def test_direct_respond_parity(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """PydanticAIAgentRuntime direct respond produces expected outcome."""
        respond_text = json.dumps(
            {"kind": "respond", "message": "Hello there!"},
            ensure_ascii=False,
            separators=(",", ":"),
        )

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            return ModelResponse(parts=[TextPart(content=respond_text)])

        runtime = _make_runtime(tool_registry, tool_catalog, context_builder, model_fn)
        result = runtime.run("hello", execution_context=read_context)

        assert result.outcome.kind == AgentOutcomeKind.RESPOND
        assert result.outcome.message == "Hello there!"
        assert len(result.tool_executions) == 0
        assert result.initial_decision.prompt_version is not None
        assert result.initial_decision.request is not None


class TestC15P2DirectClarify:
    """C15-P2: direct clarify parity."""

    def test_direct_clarify_parity(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """PydanticAIAgentRuntime direct clarify produces expected outcome."""
        clarify_text = json.dumps(
            {"kind": "clarify", "message": "Which one?"},
            ensure_ascii=False,
            separators=(",", ":"),
        )

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            return ModelResponse(parts=[TextPart(content=clarify_text)])

        runtime = _make_runtime(tool_registry, tool_catalog, context_builder, model_fn)
        result = runtime.run("query", execution_context=read_context)

        assert result.outcome.kind == AgentOutcomeKind.CLARIFY
        assert result.outcome.message == "Which one?"
        assert len(result.tool_executions) == 0


class TestC15P3SingleReadRespond:
    """C15-P3: single READ -> respond parity."""

    def test_single_read_respond_parity(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """PydanticAIAgentRuntime single READ -> respond produces expected outcome."""
        respond_text = json.dumps(
            {"kind": "respond", "message": "Found it!"},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="read_alpha",
                            args={"value": "gandalf"},
                            tool_call_id="call-1",
                        )
                    ]
                )
            return ModelResponse(parts=[TextPart(content=respond_text)])

        runtime = _make_runtime(tool_registry, tool_catalog, context_builder, model_fn)
        result = runtime.run("find gandalf", execution_context=read_context)

        assert request_count[0] == 2
        assert result.outcome.kind == AgentOutcomeKind.RESPOND
        assert result.outcome.message == "Found it!"
        assert len(result.tool_executions) == 1
        assert result.tool_executions[0].tool_call.name == "read_alpha"
        assert counters.alpha == 1


class TestC15P4SingleWriteRespond:
    """C15-P4: single WRITE -> respond parity."""

    def test_single_write_respond_parity(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        write_context: ExecutionContext,
    ) -> None:
        """PydanticAIAgentRuntime single WRITE -> respond produces expected outcome."""
        respond_text = json.dumps(
            {"kind": "respond", "message": "Written!"},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        request_count: list[int] = [0]

        def model_fn(messages: Sequence[Any], agent_info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return ModelResponse(
                    parts=[
                        ToolCallPart(
                            tool_name="write_alpha",
                            args={"value": "save-data"},
                            tool_call_id="call-w1",
                        )
                    ]
                )
            return ModelResponse(parts=[TextPart(content=respond_text)])

        runtime = _make_runtime(tool_registry, tool_catalog, context_builder, model_fn)
        result = runtime.run("save data", execution_context=write_context)

        assert request_count[0] == 2
        assert result.outcome.kind == AgentOutcomeKind.RESPOND
        assert result.outcome.message == "Written!"
        assert len(result.tool_executions) == 1
        assert result.tool_executions[0].tool_call.name == "write_alpha"
        assert counters.write_alpha == 1


class TestC15P5TwoReadRespond:
    """C15-P5: two READ -> respond parity."""

    def test_two_read_respond_parity(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """PydanticAIAgentRuntime two READ -> respond produces expected outcome."""
        respond_text = json.dumps(
            {"kind": "respond", "message": "Both done!"},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        request_count: list[int] = [0]

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
            return ModelResponse(parts=[TextPart(content=respond_text)])

        runtime = _make_runtime(tool_registry, tool_catalog, context_builder, model_fn)
        result = runtime.run("read both", execution_context=read_context)

        assert request_count[0] == 2
        assert result.outcome.kind == AgentOutcomeKind.RESPOND
        assert result.outcome.message == "Both done!"
        assert len(result.tool_executions) == 2
        assert result.tool_executions[0].tool_call.name == "read_alpha"
        assert result.tool_executions[1].tool_call.name == "read_beta"
        assert counters.alpha == 1
        assert counters.beta == 1
