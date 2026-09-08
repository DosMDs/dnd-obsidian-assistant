"""PAIM-09: Pydantic AI Ollama model — integration tests with mocked HTTP.

All tests use mocked ``httpx2`` transport — no real Ollama, no network.
Uses the **real production factory** ``build_pydantic_ai_ollama_model``,
the real ``OllamaModel``, ``OllamaProvider``, and
``PydanticAIAgentRuntime`` with mocked OpenAI-compatible HTTP responses.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any

import httpx2
import pytest

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
from dnd_assistant.errors import ModelError
from dnd_assistant.models.profiles import ModelProfile, ModelProfileRole
from dnd_assistant.models.pydantic_ai_ollama import (
    build_pydantic_ai_ollama_model,
)
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.tools.catalog import (
    ToolPublicDefinition,
    ToolRegistrySchema,
    build_tool_registry_schema,
)
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import (
    ExecutionContext,
    Permission,
    SessionMode,
    SideEffect,
)
from tests.support.pydantic_ai_runtime import (
    HandlerCounters,
    make_handler_counters,
    make_tool_registry,
)

# ==============================================================================
# Constants
# ==============================================================================

_TERMINAL_RESPONSE_TEXT = json.dumps(
    {"kind": "respond", "message": "Hello from Ollama agent"},
    ensure_ascii=False,
    separators=(",", ":"),
)

# ==============================================================================
# Mock transport helpers
# ==============================================================================


def _make_mock_transport(
    responses: list[dict[str, Any]],
    captured_requests: list[httpx2.Request] | None = None,
) -> httpx2.AsyncClient:
    """Create an ``httpx2.AsyncClient`` with a mock transport."""
    if captured_requests is None:
        captured_requests = []

    response_iter = iter(responses)

    class _MockTransport(httpx2.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
            captured_requests.append(request)
            try:
                body = next(response_iter)
            except StopIteration:
                raise httpx2.ConnectError("No more mock responses") from None
            return httpx2.Response(
                200,
                json=body,
                headers={"content-type": "application/json"},
            )

    return httpx2.AsyncClient(transport=_MockTransport())


def _make_fail_transport(
    captured_requests: list[httpx2.Request] | None = None,
) -> httpx2.AsyncClient:
    """Create an ``httpx2.AsyncClient`` that always fails with ConnectError."""
    if captured_requests is None:
        captured_requests = []

    class _AlwaysFailTransport(httpx2.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx2.Request) -> httpx2.Response:
            captured_requests.append(request)
            raise httpx2.ConnectError("Mocked connection failure")

    return httpx2.AsyncClient(transport=_AlwaysFailTransport())


# ==============================================================================
# OpenAI-compatible response builders
# ==============================================================================


def _make_chat_completion(
    content: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build an OpenAI-compatible Chat Completions response body."""
    choice: dict[str, Any] = {
        "index": 0,
        "finish_reason": "tool_calls" if tool_calls else "stop",
    }
    message: dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    choice["message"] = message
    return {
        "id": "chatcmpl-mock",
        "object": "chat.completion",
        "created": 1234567890,
        "model": "qwen3",
        "choices": [choice],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def _make_tool_call_dict(
    tool_name: str,
    args: dict[str, Any],
    call_id: str = "call-1",
) -> dict[str, Any]:
    """Build an OpenAI-compatible tool call dict."""
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": tool_name,
            "arguments": json.dumps(args, ensure_ascii=False, separators=(",", ":")),
        },
    }


# ==============================================================================
# Helpers
# ==============================================================================


def _make_tool(
    name: str,
    *,
    permission: Permission = Permission.READ,
    side_effects: list[SideEffect] | None = None,
    allowed_session_modes: list[SessionMode] | None = None,
) -> ToolPublicDefinition:
    """Build a ``ToolPublicDefinition`` with minimal boilerplate."""
    return ToolPublicDefinition(
        name=name,
        description=f"Tool {name}",
        input_schema={"type": "object", "properties": {"x": {"type": "integer"}}},
        output_schema={"type": "object", "properties": {"result": {"type": "string"}}},
        permission=permission,
        side_effects=side_effects or [],
        allowed_session_modes=allowed_session_modes or [SessionMode.NO_ACTIVE_SESSION],
    )


def _make_context(
    *,
    permission: Permission = Permission.READ,
    session_mode: SessionMode = SessionMode.NO_ACTIVE_SESSION,
    audit: AuditContext | None = None,
) -> ExecutionContext:
    """Build an ``ExecutionContext`` with minimal boilerplate."""
    return ExecutionContext(
        granted_permission=permission,
        session_mode=session_mode,
        audit=audit,
    )


def _make_runtime(
    profile: ModelProfile,
    tool_registry: ToolRegistry,
    tool_catalog: ToolRegistrySchema,
    context_builder: AgentContextBuilder,
    http_client: httpx2.AsyncClient,
    *,
    factory_call_count: list[int] | None = None,
) -> PydanticAIAgentRuntime:
    """Create a ``PydanticAIAgentRuntime`` using the **production factory**.

    The production ``build_pydantic_ai_ollama_model()`` is called to
    construct the ``OllamaModel``.  The mock ``http_client`` is injected
    by monkeypatching ``OllamaProvider`` in the production module's
    namespace so that the real provider constructor receives the mock
    transport.
    """
    from pydantic_ai.providers.ollama import OllamaProvider

    import dnd_assistant.models.pydantic_ai_ollama as _prod_factory

    _original_provider = _prod_factory.OllamaProvider

    def _mocked_provider(*, base_url: str, **kwargs: Any) -> OllamaProvider:
        if factory_call_count is not None:
            factory_call_count[0] += 1
        return _original_provider(base_url=base_url, http_client=http_client, **kwargs)

    _prod_factory.OllamaProvider = _mocked_provider  # type: ignore[assignment]

    try:
        model = build_pydantic_ai_ollama_model(profile)
    finally:
        _prod_factory.OllamaProvider = _original_provider

    assert type(model).__name__ == "OllamaModel", (
        f"expected OllamaModel, got {type(model).__name__}"
    )
    assert model.system == "ollama"

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
    return build_tool_registry_schema(tool_registry)


@pytest.fixture
def context_builder() -> AgentContextBuilder:
    """Return a minimal AgentContextBuilder that returns a fixed context."""
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
def agent_profile() -> ModelProfile:
    return ModelProfile(
        provider="ollama",
        model="qwen3",
        base_url="http://localhost:11434",
        role=ModelProfileRole.AGENT,
    )


@pytest.fixture
def factory_call_count() -> list[int]:
    return [0]


# ==============================================================================
# P9-I01 — mocked direct respond through real OllamaModel
# ==============================================================================


def test_p9_i01_mocked_direct_respond(
    counters: HandlerCounters,
    tool_registry: ToolRegistry,
    tool_catalog: ToolRegistrySchema,
    context_builder: AgentContextBuilder,
    agent_profile: ModelProfile,
    factory_call_count: list[int],
) -> None:
    """Direct respond through real ``OllamaModel`` with mocked HTTP."""
    captured: list[httpx2.Request] = []
    mock_responses = [
        _make_chat_completion(content=_TERMINAL_RESPONSE_TEXT),
    ]
    http_client = _make_mock_transport(mock_responses, captured)

    runtime = _make_runtime(
        profile=agent_profile,
        tool_registry=tool_registry,
        tool_catalog=tool_catalog,
        context_builder=context_builder,
        http_client=http_client,
        factory_call_count=factory_call_count,
    )

    ctx = _make_context()
    result = runtime.run("hello", execution_context=ctx)

    # Production factory was called exactly once
    assert factory_call_count[0] == 1, f"expected 1 factory call, got {factory_call_count[0]}"

    # Terminal outcome
    assert result.outcome.kind == AgentOutcomeKind.RESPOND
    assert "Hello from Ollama agent" in (result.final_response.message.content or "")

    # No tools executed
    assert len(result.tool_executions) == 0
    assert counters.alpha == 0

    # HTTP request evidence
    assert len(captured) == 1, f"expected 1 HTTP request, got {len(captured)}"
    req = captured[0]
    # The OpenAI SDK sends to <base_url>/chat/completions — the /v1 is in the base
    assert str(req.url) == "http://localhost:11434/v1/chat/completions", (
        f"unexpected URL: {req.url}"
    )
    assert req.method.upper() == "POST"

    # Verify model in request body
    body = json.loads(req.content)
    assert body["model"] == "qwen3"
    assert "messages" in body
    assert "tools" in body  # tools should be exposed


# ==============================================================================
# P9-I02 — mocked single READ through full PydanticAIAgentRuntime
# ==============================================================================


def test_p9_i02_mocked_single_read(
    counters: HandlerCounters,
    tool_registry: ToolRegistry,
    tool_catalog: ToolRegistrySchema,
    context_builder: AgentContextBuilder,
    agent_profile: ModelProfile,
    factory_call_count: list[int],
) -> None:
    """Single READ tool call through real ``OllamaModel`` with mocked HTTP."""
    tool_call = _make_tool_call_dict(
        tool_name="read_alpha",
        args={"value": "hello"},
        call_id="call-1",
    )
    resp1 = _make_chat_completion(content=None, tool_calls=[tool_call])
    resp2 = _make_chat_completion(content=_TERMINAL_RESPONSE_TEXT)

    captured: list[httpx2.Request] = []
    http_client = _make_mock_transport([resp1, resp2], captured)

    runtime = _make_runtime(
        profile=agent_profile,
        tool_registry=tool_registry,
        tool_catalog=tool_catalog,
        context_builder=context_builder,
        http_client=http_client,
        factory_call_count=factory_call_count,
    )

    ctx = _make_context()
    result = runtime.run("read alpha", execution_context=ctx)

    # Production factory was called exactly once
    assert factory_call_count[0] == 1

    # Terminal outcome
    assert result.outcome.kind == AgentOutcomeKind.RESPOND

    # Tool executed exactly once
    assert counters.alpha == 1, f"expected 1 read_alpha call, got {counters.alpha}"
    assert len(result.tool_executions) == 1

    # Tool execution details
    te = result.tool_executions[0]
    assert te.tool_call.name == "read_alpha"
    assert te.tool_call.call_id == "call-1"
    assert te.output is not None
    assert "alpha:hello" in str(te.output)

    # HTTP requests: 2 (tool call + terminal)
    assert len(captured) == 2, f"expected 2 HTTP requests, got {len(captured)}"

    # First request: tool call
    req1 = captured[0]
    body1 = json.loads(req1.content)
    assert body1["model"] == "qwen3"
    assert "tools" in body1

    # Second request: tool result replay — verify tool call ID and result content
    req2 = captured[1]
    body2 = json.loads(req2.content)
    assert body2["model"] == "qwen3"
    messages2 = body2.get("messages", [])
    tool_results = [m for m in messages2 if m.get("role") == "tool"]
    assert len(tool_results) == 1
    assert tool_results[0].get("tool_call_id") == "call-1"
    assert "alpha:hello" in tool_results[0].get("content", "")


# ==============================================================================
# P9-I03 — null-content + tool_calls response works
# ==============================================================================


def test_p9_i03_null_content_tool_calls(
    counters: HandlerCounters,
    tool_registry: ToolRegistry,
    tool_catalog: ToolRegistrySchema,
    context_builder: AgentContextBuilder,
    agent_profile: ModelProfile,
    factory_call_count: list[int],
) -> None:
    """Null content + tool_calls response is parsed correctly."""
    tool_call = _make_tool_call_dict(
        tool_name="read_alpha",
        args={"value": "world"},
        call_id="call-null-1",
    )
    resp1 = _make_chat_completion(content=None, tool_calls=[tool_call])
    resp2 = _make_chat_completion(content=_TERMINAL_RESPONSE_TEXT)

    captured: list[httpx2.Request] = []
    http_client = _make_mock_transport([resp1, resp2], captured)

    runtime = _make_runtime(
        profile=agent_profile,
        tool_registry=tool_registry,
        tool_catalog=tool_catalog,
        context_builder=context_builder,
        http_client=http_client,
        factory_call_count=factory_call_count,
    )

    ctx = _make_context()
    result = runtime.run("read with null content", execution_context=ctx)

    # Production factory called once
    assert factory_call_count[0] == 1

    # Tool executed
    assert counters.alpha == 1
    assert len(result.tool_executions) == 1
    assert result.outcome.kind == AgentOutcomeKind.RESPOND

    # HTTP requests == 2 (tool call + terminal)
    assert len(captured) == 2, f"expected 2 HTTP requests, got {len(captured)}"
    # captured[0] is the outgoing request, not the response.
    # The key evidence is that the runtime successfully handles null content.


# ==============================================================================
# P9-I04 — second request preserves tool result/call ID
# ==============================================================================


def test_p9_i04_second_request_preserves_tool_result(
    counters: HandlerCounters,
    tool_registry: ToolRegistry,
    tool_catalog: ToolRegistrySchema,
    context_builder: AgentContextBuilder,
    agent_profile: ModelProfile,
    factory_call_count: list[int],
) -> None:
    """Second provider request contains tool-result continuation."""
    tool_call = _make_tool_call_dict(
        tool_name="read_alpha",
        args={"value": "preserve"},
        call_id="call-preserve-1",
    )
    resp1 = _make_chat_completion(content=None, tool_calls=[tool_call])
    resp2 = _make_chat_completion(content=_TERMINAL_RESPONSE_TEXT)

    captured: list[httpx2.Request] = []
    http_client = _make_mock_transport([resp1, resp2], captured)

    runtime = _make_runtime(
        profile=agent_profile,
        tool_registry=tool_registry,
        tool_catalog=tool_catalog,
        context_builder=context_builder,
        http_client=http_client,
        factory_call_count=factory_call_count,
    )

    ctx = _make_context()
    result = runtime.run("read with preservation", execution_context=ctx)

    assert factory_call_count[0] == 1
    assert counters.alpha == 1
    assert len(result.tool_executions) == 1
    assert result.outcome.kind == AgentOutcomeKind.RESPOND

    # Second request contains tool result
    assert len(captured) >= 2
    req2_body = json.loads(captured[1].content)
    messages = req2_body.get("messages", [])

    # Find the tool result message
    tool_results = [m for m in messages if m.get("role") == "tool"]
    assert len(tool_results) == 1, f"expected 1 tool result message, got {len(tool_results)}"

    # Verify tool call ID is preserved
    tool_result = tool_results[0]
    assert tool_result.get("tool_call_id") == "call-preserve-1", (
        f"expected tool_call_id='call-preserve-1', got {tool_result.get('tool_call_id')}"
    )

    # Verify deterministic project tool-result content is present
    assert "preserve" in tool_result.get("content", ""), (
        f"expected tool result content to contain 'preserve', got {tool_result.get('content')}"
    )


# ==============================================================================
# P9-I05 — outbound tools equal issued snapshot names/order
# ==============================================================================


def test_p9_i05_outbound_tools_match_snapshot(
    counters: HandlerCounters,
    tool_registry: ToolRegistry,
    tool_catalog: ToolRegistrySchema,
    context_builder: AgentContextBuilder,
    agent_profile: ModelProfile,
    factory_call_count: list[int],
) -> None:
    """Outbound request tools match the issued snapshot names and order."""
    captured: list[httpx2.Request] = []
    mock_responses = [
        _make_chat_completion(content=_TERMINAL_RESPONSE_TEXT),
    ]
    http_client = _make_mock_transport(mock_responses, captured)

    # Spy on DndAgentRunPreparer.prepare() to capture the PreparedDndAgentRun
    from dnd_assistant.application.pydantic_ai_run_deps import DndAgentRunPreparer

    captured_prepared: list[object] = []
    original_prepare = DndAgentRunPreparer.prepare

    def _spy_prepare(self: DndAgentRunPreparer, user_input: str, **kwargs: Any) -> object:
        prepared = original_prepare(self, user_input, **kwargs)
        captured_prepared.append(prepared)
        return prepared

    DndAgentRunPreparer.prepare = _spy_prepare  # type: ignore[assignment]

    try:
        runtime = _make_runtime(
            profile=agent_profile,
            tool_registry=tool_registry,
            tool_catalog=tool_catalog,
            context_builder=context_builder,
            http_client=http_client,
            factory_call_count=factory_call_count,
        )

        ctx = _make_context()
        result = runtime.run("hello", execution_context=ctx)
    finally:
        DndAgentRunPreparer.prepare = original_prepare

    assert factory_call_count[0] == 1
    assert len(captured_prepared) == 1

    prepared = captured_prepared[0]
    snapshot_names = prepared.deps.tool_snapshot.names  # type: ignore[union-attr]

    assert len(captured) >= 1
    body = json.loads(captured[0].content)
    tools = body.get("tools", [])
    wire_tool_names = [t["function"]["name"] for t in tools]

    # With NO_ACTIVE_SESSION context, only READ tools are exposed
    # write_alpha requires ACTIVE_SESSION
    assert wire_tool_names == ["read_alpha", "read_beta"], (
        f"expected [read_alpha, read_beta], got {wire_tool_names}"
    )

    # Wire tool names/order == snapshot names/order == exposed tool names/order
    assert wire_tool_names == list(snapshot_names), (
        f"wire {wire_tool_names} != snapshot {list(snapshot_names)}"
    )
    exposed_names = tuple(t.name for t in result.initial_decision.exposed_tools)
    assert wire_tool_names == list(exposed_names), (
        f"wire {wire_tool_names} != exposed {list(exposed_names)}"
    )

    # No hidden tool appears on the wire
    assert "write_alpha" not in wire_tool_names


# ==============================================================================
# P9-I06 — temperature reaches wire
# ==============================================================================


def test_p9_i06_temperature_reaches_wire(
    counters: HandlerCounters,
    tool_registry: ToolRegistry,
    tool_catalog: ToolRegistrySchema,
    context_builder: AgentContextBuilder,
    factory_call_count: list[int],
) -> None:
    """Configured temperature reaches the HTTP request body."""
    profile = ModelProfile(
        provider="ollama",
        model="qwen3",
        base_url="http://localhost:11434",
        role=ModelProfileRole.AGENT,
        temperature=0.25,
    )

    captured: list[httpx2.Request] = []
    mock_responses = [
        _make_chat_completion(content=_TERMINAL_RESPONSE_TEXT),
    ]
    http_client = _make_mock_transport(mock_responses, captured)

    runtime = _make_runtime(
        profile=profile,
        tool_registry=tool_registry,
        tool_catalog=tool_catalog,
        context_builder=context_builder,
        http_client=http_client,
        factory_call_count=factory_call_count,
    )

    ctx = _make_context()
    runtime.run("hello", execution_context=ctx)

    assert factory_call_count[0] == 1
    assert len(captured) >= 1
    body = json.loads(captured[0].content)
    assert body.get("temperature") == 0.25, (
        f"expected temperature=0.25, got {body.get('temperature')}"
    )


# ==============================================================================
# P9-I07 — keep_alive absent from valid wire payload
# ==============================================================================


def test_p9_i07_keep_alive_absent_from_wire(
    counters: HandlerCounters,
    tool_registry: ToolRegistry,
    tool_catalog: ToolRegistrySchema,
    context_builder: AgentContextBuilder,
    agent_profile: ModelProfile,
    factory_call_count: list[int],
) -> None:
    """No ``keep_alive`` field appears in valid wire payloads."""
    captured: list[httpx2.Request] = []
    mock_responses = [
        _make_chat_completion(content=_TERMINAL_RESPONSE_TEXT),
    ]
    http_client = _make_mock_transport(mock_responses, captured)

    runtime = _make_runtime(
        profile=agent_profile,
        tool_registry=tool_registry,
        tool_catalog=tool_catalog,
        context_builder=context_builder,
        http_client=http_client,
        factory_call_count=factory_call_count,
    )

    ctx = _make_context()
    runtime.run("hello", execution_context=ctx)

    assert factory_call_count[0] == 1
    assert len(captured) >= 1
    body = json.loads(captured[0].content)
    assert "keep_alive" not in body, (
        f"unexpected keep_alive in wire payload: {body.get('keep_alive')}"
    )


# ==============================================================================
# P9-I08 — HTTP/provider failure → project ModelError, zero tools
# ==============================================================================


def test_p9_i08_provider_failure_returns_model_error(
    counters: HandlerCounters,
    tool_registry: ToolRegistry,
    tool_catalog: ToolRegistrySchema,
    context_builder: AgentContextBuilder,
    agent_profile: ModelProfile,
    factory_call_count: list[int],
) -> None:
    """HTTP provider failure surfaces as ``ModelError`` with no tool execution."""
    captured_requests: list[httpx2.Request] = []
    http_client = _make_fail_transport(captured_requests)

    runtime = _make_runtime(
        profile=agent_profile,
        tool_registry=tool_registry,
        tool_catalog=tool_catalog,
        context_builder=context_builder,
        http_client=http_client,
        factory_call_count=factory_call_count,
    )

    ctx = _make_context()

    with pytest.raises(ModelError) as exc_info:
        runtime.run("hello", execution_context=ctx)

    assert factory_call_count[0] == 1

    # No tool execution occurred
    assert counters.alpha == 0
    assert counters.beta == 0
    assert counters.write_alpha == 0

    # Literal HTTP transport attempts — the OpenAI SDK performs
    # automatic transport retries (observed: 3 attempts for a connection
    # failure). This is transport-level retry, not semantic model retry.
    assert len(captured_requests) >= 1, (
        f"expected at least 1 HTTP transport attempt, got {len(captured_requests)}"
    )

    # Exception preserves cause — exact framework type under Pydantic AI 2.39.0
    assert exc_info.value.__cause__ is not None
    from pydantic_ai.exceptions import ModelAPIError

    assert type(exc_info.value.__cause__) is ModelAPIError, (
        f"expected ModelAPIError, got {type(exc_info.value.__cause__).__name__}"
    )


# ==============================================================================
# P9-I09 — normalized reverse-proxy /v1 URL hits exact endpoint
# ==============================================================================


def test_p9_i09_reverse_proxy_v1_endpoint(
    counters: HandlerCounters,
    tool_registry: ToolRegistry,
    tool_catalog: ToolRegistrySchema,
    context_builder: AgentContextBuilder,
    factory_call_count: list[int],
) -> None:
    """Reverse-proxy base URL results in requests to the exact /v1 endpoint."""
    profile = ModelProfile(
        provider="ollama",
        model="qwen3",
        base_url="https://gateway.example/ollama",
        role=ModelProfileRole.AGENT,
    )

    captured: list[httpx2.Request] = []
    mock_responses = [
        _make_chat_completion(content=_TERMINAL_RESPONSE_TEXT),
    ]
    http_client = _make_mock_transport(mock_responses, captured)

    runtime = _make_runtime(
        profile=profile,
        tool_registry=tool_registry,
        tool_catalog=tool_catalog,
        context_builder=context_builder,
        http_client=http_client,
        factory_call_count=factory_call_count,
    )

    ctx = _make_context()
    runtime.run("hello", execution_context=ctx)

    assert factory_call_count[0] == 1
    assert len(captured) >= 1
    req = captured[0]
    # The full URL should include the reverse-proxy prefix + /v1 + /chat/completions
    full_url = str(req.url)
    assert full_url == "https://gateway.example/ollama/v1/chat/completions", (
        f"expected reverse-proxy /v1 endpoint, got {full_url}"
    )
