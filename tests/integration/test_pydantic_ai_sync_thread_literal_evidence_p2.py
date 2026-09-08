"""PAIM-C21: Literal thread identity and executor evidence — Part 2 (E06-E10).

This file contains evidence tests E06 through E10 from the PAIM-C21
correction record:

    E06 — ONE exact runtime object for sequential A/B/C runs
    E07 — ONE exact runtime for failure then recovery
    E08 — worker-thread ownership (project handler on exact worker ID)
    E09 — generic sync callback executor characterisation
    E10 — PydanticAIAgentRuntime.run() from active event loop

All tests use ``FunctionModel`` for deterministic model responses and require
no real Ollama or network access.  Thread identity is captured via
``threading.get_ident()`` and asserted as literal integer equality.
"""

from __future__ import annotations

import json
import subprocess
import sys
import threading
from collections.abc import Sequence
from contextvars import ContextVar
from datetime import UTC, datetime
from queue import Queue
from typing import Any

import pytest
from pydantic_ai.messages import (
    ModelResponse,
    TextPart,
    ToolCallPart,
)
from pydantic_ai.models import Model
from pydantic_ai.models.function import FunctionModel

from dnd_assistant.application.agent_context import AgentContextBuilder
from dnd_assistant.application.pydantic_ai_agent_runtime import (
    PydanticAIAgentRuntime,
)
from dnd_assistant.application.pydantic_ai_run_deps import (
    DndAgentRunPreparer,
    PreparedDndAgentRun,
)
from dnd_assistant.application.pydantic_ai_tool_bridge import (
    PydanticAIToolBridge,
)
from dnd_assistant.errors import ModelError
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
# Constants
# ==============================================================================

_FAKE_WORLD_TICK = 12345

# Test-local ContextVar
_TEST_CV: ContextVar[str] = ContextVar("paim_c21_p2_test_cv", default="unset")


# ==============================================================================
# Helpers
# ==============================================================================


def _capture_thread_id() -> int:
    """Return the current OS thread ID."""
    return threading.get_ident()


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
# E06 — ONE exact runtime object for sequential A/B/C runs
# ==============================================================================


class TestC21E06SameRuntimeReuse:
    """E06: one exact ``PydanticAIAgentRuntime`` object handles sequential
    A/B/C runs with fresh preparations."""

    def test_one_runtime_reused_across_runs(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        caller_thread = _capture_thread_id()
        captured_runs: list[PreparedDndAgentRun] = []

        tool_bridge = PydanticAIToolBridge(registry=tool_registry)
        preparer = DndAgentRunPreparer(
            context_builder=context_builder,
            tool_catalog=tool_catalog,
            tool_bridge=tool_bridge,
        )

        original_prepare = preparer.prepare

        def spy_prepare(user_input, *, execution_context):
            tid = _capture_thread_id()
            assert tid == caller_thread, f"Preparer on different thread {tid}"
            prepared = original_prepare(user_input, execution_context=execution_context)
            captured_runs.append(prepared)
            return prepared

        preparer.prepare = spy_prepare  # type: ignore[method-assign]

        # One stateful FunctionModel for all three runs
        run_counter: dict[str, int] = {}

        def model_fn(ctx, agent_info):
            if run_counter.get("A", 0) < 2:
                name = "A"
            elif run_counter.get("B", 0) < 2:
                name = "B"
            else:
                name = "C"
            run_counter[name] = run_counter.get(name, 0) + 1
            count = run_counter[name]
            if count == 1 and name != "C":
                return _make_tool_call_response(
                    "read_alpha",
                    tool_call_id=f"call-{name}",
                    args={"value": name},
                )
            return _make_respond_response(f"Done-{name}")

        model = FunctionModel(model_fn)
        runtime = PydanticAIAgentRuntime(run_preparer=preparer, model=model)
        runtime_id = id(runtime)

        # Run A (tool path)
        result_a = runtime.run("test A", execution_context=read_context)

        # Run B (tool path)
        result_b = runtime.run("test B", execution_context=read_context)

        # Run C (direct respond)
        result_c = runtime.run("test C", execution_context=read_context)

        assert id(runtime) == runtime_id, "Runtime object identity changed"

        # All on caller thread
        assert _capture_thread_id() == caller_thread

        # All succeeded
        assert result_a.outcome is not None
        assert result_b.outcome is not None
        assert result_c.outcome is not None

        # Fresh preparations
        assert len(captured_runs) == 3
        assert captured_runs[0].deps is not captured_runs[1].deps
        assert captured_runs[1].deps is not captured_runs[2].deps
        assert captured_runs[0].deps.policy is not captured_runs[1].deps.policy
        assert captured_runs[1].deps.policy is not captured_runs[2].deps.policy

        # Run A had a tool call, Run C was direct
        assert run_counter.get("A", 0) == 2
        assert run_counter.get("C", 0) == 1


# ==============================================================================
# E07 — ONE exact runtime for failure then recovery
# ==============================================================================


class TestC21E07FailureThenRecovery:
    """E07: one exact ``PydanticAIAgentRuntime`` survives a failed run
    then succeeds on the next run.

    Uses one stateful ``FunctionModel`` that produces a malformed response
    for run A and a valid tool-path response for run B.
    """

    def test_failure_then_recovery_on_same_runtime(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        # Register a handler to verify execution
        from pydantic import BaseModel

        from dnd_assistant.tools.types import ToolDefinition as ProjectToolDef

        class RecInput(BaseModel):
            value: str

        class RecOutput(BaseModel):
            result: str

        handler_called: bool = False

        def rec_handler(inp: RecInput, ctx: ExecutionContext) -> RecOutput:
            nonlocal handler_called
            handler_called = True
            return RecOutput(result="recovered")

        rec_def = ProjectToolDef(
            name="rec_test",
            description="Recovery test tool",
            input_schema=RecInput,
            output_schema=RecOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        )
        tool_registry.register(rec_def, rec_handler)

        from dnd_assistant.tools.catalog import build_tool_registry_schema

        updated_catalog = build_tool_registry_schema(tool_registry)

        tool_bridge = PydanticAIToolBridge(registry=tool_registry)
        preparer = DndAgentRunPreparer(
            context_builder=context_builder,
            tool_catalog=updated_catalog,
            tool_bridge=tool_bridge,
        )

        # Stateful FunctionModel: tracks which application run we're in
        application_run: int = 0
        model_request_count: int = 0

        def model_fn(ctx, agent_info):
            nonlocal application_run, model_request_count
            model_request_count += 1
            if application_run == 0:
                # Run A: first model request returns malformed response
                return ModelResponse(parts=[TextPart(content="not valid json")])
            # Run B: tool path
            if model_request_count == 1:
                return _make_tool_call_response(
                    "rec_test",
                    tool_call_id="call-rec-1",
                    args={"value": "recovery"},
                )
            return _make_respond_response("Done")

        model = FunctionModel(model_fn)
        runtime = PydanticAIAgentRuntime(run_preparer=preparer, model=model)
        runtime_id = id(runtime)

        # Run A: fails (malformed terminal response)
        application_run = 0
        with pytest.raises(ModelError):
            runtime.run("fail query", execution_context=read_context)

        assert id(runtime) == runtime_id, "Runtime object identity changed"

        # Run B: succeeds with tool path
        application_run = 1
        model_request_count = 0  # reset for new application run
        result_b = runtime.run("valid query", execution_context=read_context)

        assert result_b.outcome is not None
        assert result_b.final_response is not None
        assert handler_called, "Project handler should have executed in run B"


# ==============================================================================
# E08 — worker-thread ownership (project handler on exact worker ID)
# ==============================================================================


class TestC21E08WorkerThreadOwnership:
    """E08: the complete runtime constructed AND used inside a non-main
    worker thread executes all project callbacks on that worker thread."""

    def test_runtime_in_worker_thread_literal_identity(
        self,
    ) -> None:
        result_queue: Queue[dict[str, object]] = Queue()
        error_queue: Queue[BaseException | None] = Queue()

        main_thread = _capture_thread_id()

        def worker() -> None:
            try:
                worker_thread = _capture_thread_id()
                thread_ids: dict[str, int] = {}

                counters_local = make_handler_counters()
                registry = make_tool_registry(counters_local)

                from dnd_assistant.errors import NotFoundError
                from dnd_assistant.retrieval.service import SearchService
                from dnd_assistant.retrieval.types import SearchHit, SearchQuery
                from dnd_assistant.storage.session_events import RawSessionEvent
                from dnd_assistant.storage.session_metadata import RawSessionMetadata
                from dnd_assistant.storage.types import VaultDocument, VaultRepository
                from dnd_assistant.tools.catalog import build_tool_registry_schema

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

                ctx_builder = AgentContextBuilder(
                    search_service=_StubSearchService(),
                    vault_repository=_StubVaultRepository(),
                    session_repository=_StubSessionRepo(),
                    event_repository=_StubEventRepo(),
                    world_time_repository=_StubWorldTimeRepo(),
                )

                # Register a handler that captures its thread ID
                from pydantic import BaseModel

                class WtInput(BaseModel):
                    value: str

                class WtOutput(BaseModel):
                    result: str

                handler_thread_ids: list[int] = []

                def wt_handler(inp: WtInput, ctx: ExecutionContext) -> WtOutput:
                    handler_thread_ids.append(_capture_thread_id())
                    return WtOutput(result=f"worker:{_capture_thread_id()}")

                from dnd_assistant.tools.types import ToolDefinition as ProjectToolDef

                wt_def = ProjectToolDef(
                    name="worker_test",
                    description="Worker-thread test tool",
                    input_schema=WtInput,
                    output_schema=WtOutput,
                    permission=Permission.READ,
                    side_effects=frozenset(),
                    allowed_session_modes=frozenset(
                        {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
                    ),
                )
                registry.register(wt_def, wt_handler)

                updated_catalog = build_tool_registry_schema(registry)

                # Spy on preparer
                tool_bridge = PydanticAIToolBridge(registry=registry)
                preparer = DndAgentRunPreparer(
                    context_builder=ctx_builder,
                    tool_catalog=updated_catalog,
                    tool_bridge=tool_bridge,
                )

                original_prepare = preparer.prepare

                def spy_prepare(user_input, *, execution_context):
                    thread_ids["preparer"] = _capture_thread_id()
                    prepared = original_prepare(user_input, execution_context=execution_context)
                    original_admit = prepared.deps.policy.admit_tool_batch

                    def spy_admit(tool_calls):
                        thread_ids["policy"] = _capture_thread_id()
                        return original_admit(tool_calls)

                    prepared.deps.policy.admit_tool_batch = spy_admit  # type: ignore[method-assign]
                    return prepared

                preparer.prepare = spy_prepare  # type: ignore[method-assign]

                # Spy on bridge
                original_execute = tool_bridge.execute

                def spy_execute(snapshot, tool_call, *, execution_context):
                    thread_ids["bridge"] = _capture_thread_id()
                    return original_execute(
                        snapshot, tool_call, execution_context=execution_context
                    )

                tool_bridge.execute = spy_execute  # type: ignore[method-assign]

                model_request_count: int = 0

                def model_fn(ctx, agent_info):
                    nonlocal model_request_count
                    model_request_count += 1
                    if model_request_count == 1:
                        return _make_tool_call_response(
                            "worker_test",
                            tool_call_id="call-w-1",
                            args={"value": "hello"},
                        )
                    return _make_respond_response("Done")

                model = FunctionModel(model_fn)
                runtime = PydanticAIAgentRuntime(run_preparer=preparer, model=model)

                exec_context = _make_context(
                    permission=Permission.READ,
                    session_mode=SessionMode.NO_ACTIVE_SESSION,
                )

                result = runtime.run("worker query", execution_context=exec_context)

                result_queue.put(
                    {
                        "success": True,
                        "model_requests": model_request_count,
                        "result_outcome": result.outcome is not None,
                        "worker_thread": worker_thread,
                        "preparer_thread": thread_ids.get("preparer"),
                        "policy_thread": thread_ids.get("policy"),
                        "bridge_thread": thread_ids.get("bridge"),
                        "handler_thread": handler_thread_ids[0] if handler_thread_ids else None,
                    }
                )
            except BaseException as exc:
                error_queue.put(exc)
            finally:
                error_queue.put(None)

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        t.join(timeout=30)

        errors: list[BaseException] = []
        while not error_queue.empty():
            err = error_queue.get_nowait()
            if err is not None:
                errors.append(err)

        assert not errors, f"Worker thread raised: {errors}"

        results: dict[str, object] = result_queue.get(timeout=5)
        assert results.get("success") is True
        assert results.get("model_requests") == 2
        assert results.get("result_outcome") is True

        worker_thread = results["worker_thread"]
        assert worker_thread != main_thread, "Worker thread must differ from main thread"

        # All project-path points must be on the worker thread
        for key in ("preparer_thread", "policy_thread", "bridge_thread", "handler_thread"):
            tid = results.get(key)
            assert tid == worker_thread, (
                f"{key} thread ID {tid} differs from worker thread {worker_thread}"
            )


# ==============================================================================
# E09 — generic sync callback executor characterisation
# ==============================================================================


class TestC21E09GenericSyncCallback:
    """E09: characterise generic Pydantic AI synchronous function tool
    callback behavior — whether it is dispatched through
    ``run_in_executor`` depends on the framework version and tool type."""

    def test_generic_sync_callback_executor_route(
        self,
    ) -> None:
        """Characterise the generic sync callback executor route.

        In Pydantic AI 2.39.0, ``@agent.tool_plain`` sync callbacks are
        handled inline by the framework and may NOT be dispatched through
        ``pydantic_ai._utils.run_in_executor``.  This test captures the
        actual behavior without overclaiming.
        """
        import pydantic_ai._utils as pai_utils

        original_run_in_executor = pai_utils.run_in_executor
        executor_callables: list[str] = []

        async def spy_run_in_executor(func, *args, **kwargs):
            fn_name = getattr(func, "__name__", str(func))
            executor_callables.append(fn_name)
            return await original_run_in_executor(func, *args, **kwargs)

        pai_utils.run_in_executor = spy_run_in_executor  # type: ignore[assignment]

        try:
            caller_thread = _capture_thread_id()
            tool_threads: list[int] = []

            def sync_tool(value: str) -> str:
                tool_threads.append(_capture_thread_id())
                return f"hello from thread {_capture_thread_id()}"

            from pydantic_ai import Agent

            agent = Agent(
                "test",
                retries={"tools": 0},
                deps_type=object,
            )
            agent.tool_plain()(sync_tool)

            result = agent.run_sync("call the tool", deps=object())

            assert len(tool_threads) >= 1, "Tool should have been called"

            # Characterise: the generic sync callback may or may not go
            # through run_in_executor depending on framework internals.
            # Record the observed behavior without asserting a specific route.
            print(
                f"P10-E09: caller thread={caller_thread}, "
                f"sync tool thread={tool_threads[0]}, "
                f"different={tool_threads[0] != caller_thread}, "
                f"executor_callables={executor_callables}"
            )

            assert result.output is not None
        finally:
            pai_utils.run_in_executor = original_run_in_executor


# ==============================================================================
# E10 — PydanticAIAgentRuntime.run() from active event loop
# ==============================================================================


class TestC21E10ActiveEventLoop:
    """E10: ``PydanticAIAgentRuntime.run()`` cannot be called from code
    already running an asyncio event loop."""

    def test_runtime_run_from_active_loop(
        self,
    ) -> None:
        """Prove that calling ``PydanticAIAgentRuntime.run()`` from within
        an already-running event loop raises an appropriate error.

        Uses a subprocess to avoid contaminating pytest's event loop.
        """
        code = """
import asyncio
import sys

async def main():
    from dnd_assistant.application.pydantic_ai_agent_runtime import (
        PydanticAIAgentRuntime,
    )
    from dnd_assistant.application.pydantic_ai_run_deps import (
        DndAgentRunPreparer,
    )
    from dnd_assistant.application.pydantic_ai_tool_bridge import (
        PydanticAIToolBridge,
    )
    from dnd_assistant.application.agent_context import AgentContextBuilder
    from dnd_assistant.tools.registry import ToolRegistry
    from dnd_assistant.tools.types import (
        ExecutionContext,
        Permission,
        SessionMode,
    )
    from dnd_assistant.tools.catalog import build_tool_registry_schema
    from pydantic_ai.models.function import FunctionModel
    from pydantic_ai.messages import ModelResponse, TextPart
    from tests.support.pydantic_ai_runtime import (
        make_handler_counters,
        make_tool_registry,
    )
    from collections.abc import Sequence

    counters = make_handler_counters()
    registry = make_tool_registry(counters)
    catalog = build_tool_registry_schema(registry)

    from dnd_assistant.errors import NotFoundError
    from dnd_assistant.retrieval.service import SearchService
    from dnd_assistant.retrieval.types import SearchHit, SearchQuery
    from dnd_assistant.storage.session_events import RawSessionEvent
    from dnd_assistant.storage.session_metadata import RawSessionMetadata
    from dnd_assistant.storage.types import VaultDocument, VaultRepository

    class _StubSearchService(SearchService):
        def search(self, query, *, limit=5):
            return []

    class _StubVaultRepository(VaultRepository):
        def get_entity(self, entity_id):
            raise ValueError("unexpected call")

    class _StubSessionRepo:
        def get_active_session(self):
            return None

    class _StubEventRepo:
        def list_events(self, session_id):
            return []

    class _StubWorldTimeRepo:
        def get_current_world_time(self):
            raise NotFoundError("no world time")

    ctx_builder = AgentContextBuilder(
        search_service=_StubSearchService(),
        vault_repository=_StubVaultRepository(),
        session_repository=_StubSessionRepo(),
        event_repository=_StubEventRepo(),
        world_time_repository=_StubWorldTimeRepo(),
    )

    tool_bridge = PydanticAIToolBridge(registry=registry)
    preparer = DndAgentRunPreparer(
        context_builder=ctx_builder,
        tool_catalog=catalog,
        tool_bridge=tool_bridge,
    )

    def model_fn(ctx, info):
        return ModelResponse(parts=[TextPart(content='{"kind": "respond", "message": "hello"}')])

    model = FunctionModel(model_fn)
    runtime = PydanticAIAgentRuntime(run_preparer=preparer, model=model)

    exec_ctx = ExecutionContext(
        granted_permission=Permission.READ,
        session_mode=SessionMode.NO_ACTIVE_SESSION,
    )

    try:
        result = runtime.run("test", execution_context=exec_ctx)
        print(f"UNEXPECTED_SUCCESS: {result}")
        sys.exit(1)
    except RuntimeError as e:
        print(f"EXPECTED_ERROR: {type(e).__name__}: {e}")
        sys.exit(0)
    except Exception as e:
        print(f"UNEXPECTED_ERROR_TYPE: {type(e).__name__}: {e}")
        sys.exit(1)

asyncio.run(main())
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            capture_output=True,
            text=True,
            timeout=30,
        )

        assert "EXPECTED_ERROR" in result.stdout, (
            f"Expected RuntimeError from active event loop. "
            f"stdout: {result.stdout}, stderr: {result.stderr}"
        )
        assert "UNEXPECTED_SUCCESS" not in result.stdout
        assert result.returncode == 0, (
            f"Subprocess exited with code {result.returncode}. "
            f"stdout: {result.stdout}, stderr: {result.stderr}"
        )
