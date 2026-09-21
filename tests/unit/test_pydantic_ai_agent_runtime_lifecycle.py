"""RM-03: provider-neutral managed model/provider lifecycle evidence.

These tests are deterministic and fully offline: no Ollama server, no DeepSeek
credential, no network.  They prove that ``PydanticAIAgentRuntime.run()`` keeps
its public synchronous contract while executing one managed public
``async with Agent`` / ``await Agent.run(...)`` run, so provider-owned HTTP
clients are closed deterministically.

Composition of evidence
───────────────────────

* Model-context enter/exit counts prove the runtime owns the managed context
  (L1-L4).
* Real (offline) ``OllamaModel`` / ``OpenAIChatModel`` provider clients are
  proven to close through that same public ``Model`` / ``Provider`` context
  (L7, L8).
* A project-owned re-entry guard rejects nested synchronous runs and running
  event loops, and always resets (L5, L5b, L5c).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import pytest
from pydantic_ai.exceptions import ModelAPIError
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
from pydantic_ai.models.function import FunctionModel
from pydantic_ai.models.wrapper import WrapperModel
from pydantic_ai.toolsets import WrapperToolset

from dnd_assistant.application.agent_context import AgentContextBuilder
from dnd_assistant.application.pydantic_ai_agent_runtime import (
    PydanticAIAgentRuntime,
)
from dnd_assistant.application.pydantic_ai_run_deps import DndAgentRunPreparer
from dnd_assistant.application.pydantic_ai_tool_bridge import PydanticAIToolBridge
from dnd_assistant.errors import DndAssistantError, ModelError
from dnd_assistant.models.profiles import ModelProfile, ModelProfileRole, ReasoningEffort
from dnd_assistant.tools.catalog import ToolRegistrySchema, build_tool_registry_schema
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import ExecutionContext, Permission, SessionMode
from tests.support.context_builder_doubles import make_stub_context_builder
from tests.support.pydantic_ai_runtime import (
    READ_ALPHA_DEF,
    HandlerCounters,
    ToolOutput,
    make_handler_counters,
    make_tool_registry,
)

pytestmark = pytest.mark.provider_upgrade

_ALPHA_INPUT = {"value": "x"}


# ── Deterministic model wrappers ───────────────────────────────────────────


class _LifecycleModel(WrapperModel):
    """Function model wrapper that counts managed context entry/exit."""

    def __init__(self, wrapped: Any) -> None:
        super().__init__(wrapped=wrapped)
        self.enter_count = 0
        self.exit_count = 0

    async def __aenter__(self) -> _LifecycleModel:
        self.enter_count += 1
        await self.wrapped.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> bool | None:
        try:
            return await self.wrapped.__aexit__(*args)
        finally:
            self.exit_count += 1


@dataclass
class _CountingToolset(WrapperToolset[object]):
    """Per-run toolset wrapper that counts entry/exit."""

    def __post_init__(self) -> None:
        self.enter_count = 0
        self.exit_count = 0

    async def __aenter__(self) -> _CountingToolset:
        self.enter_count += 1
        await self.wrapped.__aenter__()
        return self

    async def __aexit__(self, *args: Any) -> bool | None:
        self.exit_count += 1
        return await self.wrapped.__aexit__(*args)


# ── Fixtures / helpers ─────────────────────────────────────────────────────


@pytest.fixture()
def counters() -> HandlerCounters:
    return make_handler_counters()


@pytest.fixture()
def tool_registry(counters: HandlerCounters) -> ToolRegistry:
    return make_tool_registry(counters)


@pytest.fixture()
def tool_catalog(tool_registry: ToolRegistry) -> ToolRegistrySchema:
    return build_tool_registry_schema(tool_registry)


@pytest.fixture()
def context_builder() -> AgentContextBuilder:
    return make_stub_context_builder()


@pytest.fixture()
def read_context() -> ExecutionContext:
    return ExecutionContext(
        granted_permission=Permission.READ,
        session_mode=SessionMode.NO_ACTIVE_SESSION,
    )


def _respond(content: str) -> ModelResponse:
    payload = json.dumps(
        {"kind": "respond", "message": content},
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return ModelResponse(parts=[TextPart(content=payload)])


def _tool_call(tool_name: str, *, tool_call_id: str, args: dict[str, Any]) -> ModelResponse:
    return ModelResponse(
        parts=[ToolCallPart(tool_name=tool_name, args=args, tool_call_id=tool_call_id)]
    )


def _make_runtime(
    model: Any,
    tool_registry: ToolRegistry,
    tool_catalog: ToolRegistrySchema,
    context_builder: AgentContextBuilder,
) -> PydanticAIAgentRuntime:
    bridge = PydanticAIToolBridge(registry=tool_registry)
    preparer = DndAgentRunPreparer(
        context_builder=context_builder,
        tool_catalog=tool_catalog,
        tool_bridge=bridge,
    )
    return PydanticAIAgentRuntime(run_preparer=preparer, model=model)


def _cause_chain_text(exc: BaseException) -> str:
    parts: list[str] = []
    current: BaseException | None = exc
    while current is not None:
        parts.append(str(current))
        current = current.__cause__ or current.__context__
    return " | ".join(parts)


# ── L1: direct-text success ────────────────────────────────────────────────


class TestManagedContextSuccess:
    def test_model_context_entered_and_exited_once(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        model = _LifecycleModel(FunctionModel(lambda messages, info: _respond("Done!")))
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        result = runtime.run("test", execution_context=read_context)

        assert model.enter_count == 1
        assert model.exit_count == 1
        assert result.outcome.message == "Done!"


# ── L2: tool continuation stays inside one open context ────────────────────


class TestManagedContextToolContinuation:
    def test_context_open_across_all_model_requests(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        request_count = [0]
        observed: list[tuple[int, int]] = []
        holder: list[_LifecycleModel] = []

        def model_fn(messages: Sequence[Any], info: Any) -> ModelResponse:
            observed.append((holder[0].enter_count, holder[0].exit_count))
            request_count[0] += 1
            if request_count[0] == 1:
                return _tool_call("read_alpha", tool_call_id="call-1", args=_ALPHA_INPUT)
            return _respond("Done!")

        model = _LifecycleModel(FunctionModel(model_fn))
        holder.append(model)
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        result = runtime.run("test", execution_context=read_context)

        assert request_count[0] == 2
        assert len(result.tool_executions) == 1
        assert counters.alpha == 1
        assert observed == [(1, 0), (1, 0)]
        assert model.enter_count == 1
        assert model.exit_count == 1


# ── L3: framework/model failure ────────────────────────────────────────────


class TestManagedContextModelFailure:
    def test_context_exits_on_model_error(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        def model_fn(messages: Sequence[Any], info: Any) -> ModelResponse:
            raise ModelAPIError("test-model", "simulated model failure")

        model = _LifecycleModel(FunctionModel(model_fn))
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        with pytest.raises(ModelError, match="Pydantic AI model request failed"):
            runtime.run("test", execution_context=read_context)

        assert model.enter_count == 1
        assert model.exit_count == 1


# ── L4: tool/application exception ─────────────────────────────────────────


class TestManagedContextToolException:
    def test_context_exits_on_tool_exception(
        self,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        registry = ToolRegistry()

        def raising_handler(inp: Any, ctx: Any) -> ToolOutput:
            raise DndAssistantError("handler boom")

        registry.register(READ_ALPHA_DEF, raising_handler)
        catalog = build_tool_registry_schema(registry)

        def model_fn(messages: Sequence[Any], info: Any) -> ModelResponse:
            return _tool_call("read_alpha", tool_call_id="call-1", args=_ALPHA_INPUT)

        model = _LifecycleModel(FunctionModel(model_fn))
        runtime = _make_runtime(model, registry, catalog, context_builder)

        with pytest.raises(DndAssistantError) as exc_info:
            runtime.run("test", execution_context=read_context)

        assert model.enter_count == 1
        assert model.exit_count == 1
        assert "handler boom" in _cause_chain_text(exc_info.value)


# ── L5: active event loop fail-closed ──────────────────────────────────────


class TestActiveEventLoopFailClosed:
    def test_run_rejected_from_running_event_loop(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        model = _LifecycleModel(FunctionModel(lambda messages, info: _respond("Done!")))
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        async def _call() -> None:
            with pytest.raises(RuntimeError) as exc_info:
                runtime.run("test", execution_context=read_context)
            # Must be the project-owned guard, not asyncio.run's own error.
            assert str(exc_info.value).startswith("PydanticAIAgentRuntime.run()")

        asyncio.run(_call())
        assert model.enter_count == 0
        assert model.exit_count == 0


# ── L5b/L5c: project-owned re-entry guard ──────────────────────────────────


class TestProjectSyncRunGuard:
    def test_nested_run_rejected_and_guard_resets(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        from dnd_assistant.application import pydantic_ai_agent_runtime as runtime_mod

        model = _LifecycleModel(FunctionModel(lambda messages, info: _respond("Done!")))
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        outer_token = runtime_mod._acquire_sync_run_guard()
        try:
            with pytest.raises(RuntimeError, match="already-running agent run"):
                runtime.run("test", execution_context=read_context)
            # The nested attempt must not have reached the model.
            assert model.enter_count == 0
        finally:
            runtime_mod._IN_PROJECT_SYNC_RUN.reset(outer_token)

        # After reset, a fresh top-level run succeeds and the guard is clear.
        result = runtime.run("test", execution_context=read_context)
        assert result.outcome.message == "Done!"
        assert model.enter_count == 1
        assert model.exit_count == 1
        assert runtime_mod._IN_PROJECT_SYNC_RUN.get() is False

    def test_guard_resets_after_failure(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        from dnd_assistant.application import pydantic_ai_agent_runtime as runtime_mod

        def failing_fn(messages: Sequence[Any], info: Any) -> ModelResponse:
            raise ModelAPIError("test-model", "boom")

        failing = _LifecycleModel(FunctionModel(failing_fn))
        runtime = _make_runtime(failing, tool_registry, tool_catalog, context_builder)

        with pytest.raises(ModelError):
            runtime.run("test", execution_context=read_context)

        assert runtime_mod._IN_PROJECT_SYNC_RUN.get() is False
        assert failing.exit_count == 1


# ── L6: per-run external toolset entered exactly once ──────────────────────


class TestPerRunToolsetLifecycle:
    def test_external_toolset_entered_once(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: list[_CountingToolset] = []
        original = PydanticAIToolBridge.to_external_toolset

        def wrapper(self: PydanticAIToolBridge, snapshot: Any) -> Any:
            counting = _CountingToolset(wrapped=original(self, snapshot))
            captured.append(counting)
            return counting

        monkeypatch.setattr(PydanticAIToolBridge, "to_external_toolset", wrapper)

        request_count = [0]

        def model_fn(messages: Sequence[Any], info: Any) -> ModelResponse:
            request_count[0] += 1
            if request_count[0] == 1:
                return _tool_call("read_alpha", tool_call_id="call-1", args=_ALPHA_INPUT)
            return _respond("Done!")

        model = _LifecycleModel(FunctionModel(model_fn))
        runtime = _make_runtime(model, tool_registry, tool_catalog, context_builder)

        runtime.run("test", execution_context=read_context)

        assert len(captured) == 1
        assert captured[0].enter_count == 1
        assert captured[0].exit_count == 1
        assert counters.alpha == 1


# ── L7/L8: provider-owned clients close through the generic mechanism ──────


class TestProviderClientLifecycle:
    """The public ``async with model`` context closes provider-owned clients.

    The runtime enters this exact context (L1-L4); these tests prove the
    context closes the provider client for both the accepted Ollama provider and
    the RM-02 DeepSeek provider, offline and without credentials.
    """

    def test_ollama_provider_client_closed(self) -> None:
        from dnd_assistant.models.pydantic_ai_ollama import build_pydantic_ai_ollama_model

        profile = ModelProfile(
            provider="ollama",
            model="test-model",
            base_url="http://localhost:11434",
            role=ModelProfileRole.AGENT,
        )
        model = build_pydantic_ai_ollama_model(profile)
        provider = model.provider
        assert provider is not None
        client = provider.client
        assert client.is_closed() is False

        async def _enter_exit() -> None:
            async with model:
                pass

        asyncio.run(_enter_exit())
        assert client.is_closed() is True

    def test_deepseek_provider_client_closed(self) -> None:
        from pydantic_ai.providers.deepseek import DeepSeekProvider

        from dnd_assistant.models.pydantic_ai_deepseek import (
            build_pydantic_ai_deepseek_model,
        )

        profile = ModelProfile(
            provider="deepseek",
            model="deepseek-flash",
            base_url="https://api.deepseek.com",
            role=ModelProfileRole.AGENT,
            thinking=True,
            reasoning_effort=ReasoningEffort.HIGH,
        )
        model = build_pydantic_ai_deepseek_model(
            profile, provider=DeepSeekProvider(api_key="offline-dummy-key")
        )
        provider = model.provider
        assert provider is not None
        client = provider.client
        assert client.is_closed() is False

        async def _enter_exit() -> None:
            async with model:
                pass

        asyncio.run(_enter_exit())
        assert client.is_closed() is True
