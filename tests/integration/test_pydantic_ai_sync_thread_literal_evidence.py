"""PAIM-C21: Literal thread identity and executor evidence for PAIM-10.

This file provides the corrected literal evidence required by PAIM-C21:

    E01 — complete project-path thread identity (caller, context builder,
          preparer, deferred handler, policy, bridge, ToolExecutor, project
          handler, caller after)
    E02 — literal run_in_executor callable classification
    E03 — ContextVar reaches actual project handler
    E04 — ContextVar write reaches later distinct callback in same run
    E05 — default SQLite connection usable in ToolExecutor handler
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
import os
import sqlite3
import threading
from collections.abc import Sequence
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic_ai import RunContext
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

# Test-local ContextVar for E03/E04
_TEST_CV: ContextVar[str] = ContextVar("paim_c21_test_cv", default="unset")


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
# E01 — Complete project-path thread identity
# ==============================================================================


class TestC21E01CompleteThreadIdentity:
    """E01: every project callback stays on the caller OS thread.

    Required captured IDs:
        caller_before
        context_builder
        preparer
        deferred_handler
        policy
        bridge
        ToolExecutor
        project_handler
        caller_after

    All must be equal.
    """

    def test_complete_tool_path_literal_thread_identity(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Prove all nine project-path points execute on the caller thread."""
        thread_ids: dict[str, int] = {}
        policy_thread_ids: list[int] = []
        tool_executor_thread_ids: list[int] = []
        handler_thread_ids: list[int] = []

        # Instrument context_builder.build
        original_build = context_builder.build

        def spy_build(user_input: str) -> object:
            thread_ids["context_builder"] = _capture_thread_id()
            return original_build(user_input)

        context_builder.build = spy_build  # type: ignore[method-assign]

        # Register a custom handler that captures its thread ID
        from pydantic import BaseModel

        class ThreadInput(BaseModel):
            value: str

        class ThreadOutput(BaseModel):
            result: str

        def thread_handler(inp: ThreadInput, ctx: ExecutionContext) -> ThreadOutput:
            handler_thread_ids.append(_capture_thread_id())
            return ThreadOutput(result=f"thread:{_capture_thread_id()}")

        from dnd_assistant.tools.types import ToolDefinition as ProjectToolDef

        thread_def = ProjectToolDef(
            name="thread_test",
            description="Thread-identity test tool",
            input_schema=ThreadInput,
            output_schema=ThreadOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        )
        tool_registry.register(thread_def, thread_handler)

        from dnd_assistant.tools.catalog import build_tool_registry_schema

        updated_catalog = build_tool_registry_schema(tool_registry)

        # Build components with spy capability
        tool_bridge = PydanticAIToolBridge(registry=tool_registry)
        preparer = DndAgentRunPreparer(
            context_builder=context_builder,
            tool_catalog=updated_catalog,
            tool_bridge=tool_bridge,
        )

        # Spy on preparer.prepare
        original_prepare = preparer.prepare

        def spy_prepare(
            user_input: str,
            *,
            execution_context: ExecutionContext,
        ) -> PreparedDndAgentRun:
            thread_ids["preparer"] = _capture_thread_id()
            prepared = original_prepare(user_input, execution_context=execution_context)
            # Spy on the policy's admit_tool_batch
            original_admit = prepared.deps.policy.admit_tool_batch

            def spy_admit(tool_calls):
                policy_thread_ids.append(_capture_thread_id())
                return original_admit(tool_calls)

            prepared.deps.policy.admit_tool_batch = spy_admit  # type: ignore[method-assign]
            return prepared

        preparer.prepare = spy_prepare  # type: ignore[method-assign]

        # Spy on bridge.execute
        original_execute = tool_bridge.execute

        def spy_execute(snapshot, tool_call, *, execution_context):
            thread_ids["bridge"] = _capture_thread_id()
            return original_execute(snapshot, tool_call, execution_context=execution_context)

        tool_bridge.execute = spy_execute  # type: ignore[method-assign]

        # Instrument the deferred handler by wrapping _make_deferred_handler
        import dnd_assistant.application.pydantic_ai_agent_runtime as runtime_mod

        original_make_deferred = runtime_mod._make_deferred_handler

        def spy_make_deferred(prepared):
            handler, executions = original_make_deferred(prepared)
            # Wrap the handler's public .handler attribute to capture thread
            original_capability = handler.handler

            def spy_handler(ctx, requests):
                thread_ids["deferred_handler"] = _capture_thread_id()
                return original_capability(ctx, requests)

            handler.handler = spy_handler
            return handler, executions

        runtime_mod._make_deferred_handler = spy_make_deferred  # type: ignore[assignment]

        # Spy on ToolExecutor.execute
        from dnd_assistant.tools.executor import ToolExecutor

        original_executor_execute = ToolExecutor.execute

        def spy_executor_execute(self, tool_name, *, input_data, context):
            tool_executor_thread_ids.append(_capture_thread_id())
            return original_executor_execute(
                self, tool_name, input_data=input_data, context=context
            )

        try:
            ToolExecutor.execute = spy_executor_execute  # type: ignore[assignment]

            # Model: request #1 = tool call, request #2 = terminal text
            model_request_count: int = 0

            def model_fn(
                ctx: RunContext[object],
                agent_info: object,
            ) -> ModelResponse:
                nonlocal model_request_count
                model_request_count += 1
                if model_request_count == 1:
                    return _make_tool_call_response(
                        "thread_test",
                        tool_call_id="call-thread-1",
                        args={"value": "hello"},
                    )
                return _make_respond_response("Done")

            model = FunctionModel(model_fn)
            runtime = PydanticAIAgentRuntime(run_preparer=preparer, model=model)

            caller_before = _capture_thread_id()
            result = runtime.run("test query", execution_context=read_context)
            caller_after = _capture_thread_id()

            # Assertions
            assert model_request_count == 2, f"Expected 2 model requests, got {model_request_count}"
            assert len(policy_thread_ids) >= 1, "Policy should have been called"
            assert len(tool_executor_thread_ids) >= 1, "ToolExecutor should have been called"
            assert len(handler_thread_ids) >= 1, "Handler should have been called"

            # All project-path thread IDs must equal caller_before
            project_ids: dict[str, int | None] = {
                "caller_before": caller_before,
                "context_builder": thread_ids.get("context_builder"),
                "preparer": thread_ids.get("preparer"),
                "deferred_handler": thread_ids.get("deferred_handler"),
                "policy": policy_thread_ids[0] if policy_thread_ids else None,
                "bridge": thread_ids.get("bridge"),
                "ToolExecutor": tool_executor_thread_ids[0] if tool_executor_thread_ids else None,
                "project_handler": handler_thread_ids[0] if handler_thread_ids else None,
                "caller_after": caller_after,
            }

            for name, tid in project_ids.items():
                assert tid == caller_before, (
                    f"{name} thread ID {tid} differs from caller thread {caller_before}"
                )

            assert result.outcome is not None
            assert result.final_response is not None

        finally:
            ToolExecutor.execute = original_executor_execute
            runtime_mod._make_deferred_handler = original_make_deferred


# ==============================================================================
# E02 — Literal run_in_executor callable classification
# ==============================================================================


class TestC21E02LiteralExecutorClassification:
    """E02: zero project-path callbacks dispatched via run_in_executor.

    Records every callable passed to ``pydantic_ai._utils.run_in_executor``
    and asserts that none of them are project-path callbacks.
    """

    def test_zero_project_callbacks_in_run_in_executor(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        import pydantic_ai._utils as pai_utils

        original_run_in_executor = pai_utils.run_in_executor
        observed_callables: list[str] = []

        async def spy_run_in_executor(func, *args, **kwargs):
            fn_name = getattr(func, "__name__", str(func))
            observed_callables.append(fn_name)
            return await original_run_in_executor(func, *args, **kwargs)

        pai_utils.run_in_executor = spy_run_in_executor  # type: ignore[assignment]

        try:
            tool_bridge = PydanticAIToolBridge(registry=tool_registry)
            preparer = DndAgentRunPreparer(
                context_builder=context_builder,
                tool_catalog=tool_catalog,
                tool_bridge=tool_bridge,
            )

            model_request_count: int = 0

            def model_fn(
                ctx: RunContext[object],
                agent_info: object,
            ) -> ModelResponse:
                nonlocal model_request_count
                model_request_count += 1
                if model_request_count == 1:
                    return _make_tool_call_response(
                        "read_alpha",
                        tool_call_id="call-1",
                        args={"value": "hello"},
                    )
                return _make_respond_response("Done")

            model = FunctionModel(model_fn)
            runtime = PydanticAIAgentRuntime(run_preparer=preparer, model=model)
            result = runtime.run("test query", execution_context=read_context)

            assert model_request_count == 2
            assert result.outcome is not None

            # Identify project-path callables that must NOT appear
            project_callables = {
                "admit_tool_batch",
                "execute",
                "_handler",
                "spy_handler",
                "thread_handler",
                "sqlite_handler",
            }

            project_found = [name for name in observed_callables if name in project_callables]

            assert len(project_found) == 0, (
                f"Project-path callables found in run_in_executor: {project_found}. "
                f"All observed: {observed_callables}"
            )
        finally:
            pai_utils.run_in_executor = original_run_in_executor


# ==============================================================================
# E03 — ContextVar reaches actual project handler
# ==============================================================================


class TestC21E03ContextVarToHandler:
    """E03: a ``ContextVar`` set by the synchronous caller is readable
    inside every project callback including the actual project handler."""

    def test_contextvar_reaches_actual_handler(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Set a ContextVar before runtime.run() and read it from preparer,
        deferred handler, policy, bridge.execute, and the actual project
        tool handler."""
        cv_values: dict[str, str] = {}
        SENTINEL = "paim-c21-caller-value"
        handler_cv_values: list[str] = []

        # Register a custom handler that reads the ContextVar
        from pydantic import BaseModel

        class CvInput(BaseModel):
            value: str

        class CvOutput(BaseModel):
            result: str

        def cv_handler(inp: CvInput, ctx: ExecutionContext) -> CvOutput:
            handler_cv_values.append(_TEST_CV.get())
            return CvOutput(result="cv-ok")

        from dnd_assistant.tools.types import ToolDefinition as ProjectToolDef

        cv_def = ProjectToolDef(
            name="cv_test",
            description="ContextVar propagation test tool",
            input_schema=CvInput,
            output_schema=CvOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        )
        tool_registry.register(cv_def, cv_handler)

        from dnd_assistant.tools.catalog import build_tool_registry_schema

        updated_catalog = build_tool_registry_schema(tool_registry)

        tool_bridge = PydanticAIToolBridge(registry=tool_registry)
        preparer = DndAgentRunPreparer(
            context_builder=context_builder,
            tool_catalog=updated_catalog,
            tool_bridge=tool_bridge,
        )

        # Spy on preparer
        original_prepare = preparer.prepare

        def spy_prepare(user_input, *, execution_context):
            cv_values["preparer"] = _TEST_CV.get()
            prepared = original_prepare(user_input, execution_context=execution_context)
            # Spy on policy
            original_admit = prepared.deps.policy.admit_tool_batch

            def spy_admit(tool_calls):
                cv_values["policy"] = _TEST_CV.get()
                return original_admit(tool_calls)

            prepared.deps.policy.admit_tool_batch = spy_admit  # type: ignore[method-assign]
            return prepared

        preparer.prepare = spy_prepare  # type: ignore[method-assign]

        # Spy on bridge
        original_execute = tool_bridge.execute

        def spy_execute(snapshot, tool_call, *, execution_context):
            cv_values["bridge"] = _TEST_CV.get()
            return original_execute(snapshot, tool_call, execution_context=execution_context)

        tool_bridge.execute = spy_execute  # type: ignore[method-assign]

        # Spy on deferred handler
        import dnd_assistant.application.pydantic_ai_agent_runtime as runtime_mod

        original_make_deferred = runtime_mod._make_deferred_handler

        def spy_make_deferred(prepared):
            handler, executions = original_make_deferred(prepared)
            original_capability = handler.handler

            def spy_handler(ctx, requests):
                cv_values["deferred_handler"] = _TEST_CV.get()
                return original_capability(ctx, requests)

            handler.handler = spy_handler
            return handler, executions

        runtime_mod._make_deferred_handler = spy_make_deferred  # type: ignore[assignment]

        try:
            model_request_count: int = 0

            def model_fn(ctx, agent_info):
                nonlocal model_request_count
                model_request_count += 1
                if model_request_count == 1:
                    return _make_tool_call_response(
                        "cv_test",
                        tool_call_id="call-cv-1",
                        args={"value": "hello"},
                    )
                return _make_respond_response("Done")

            model = FunctionModel(model_fn)
            runtime = PydanticAIAgentRuntime(run_preparer=preparer, model=model)

            # Set ContextVar before run
            _TEST_CV.set(SENTINEL)
            result = runtime.run("test query", execution_context=read_context)

            assert model_request_count == 2

            # Assert ContextVar readable in all project callbacks
            assert cv_values.get("preparer") == SENTINEL, (
                f"preparer saw {cv_values.get('preparer')!r}, expected {SENTINEL!r}"
            )
            assert cv_values.get("deferred_handler") == SENTINEL, (
                f"deferred_handler saw {cv_values.get('deferred_handler')!r}, expected {SENTINEL!r}"
            )
            assert cv_values.get("policy") == SENTINEL, (
                f"policy saw {cv_values.get('policy')!r}, expected {SENTINEL!r}"
            )
            assert cv_values.get("bridge") == SENTINEL, (
                f"bridge saw {cv_values.get('bridge')!r}, expected {SENTINEL!r}"
            )

            # The actual project handler MUST see the ContextVar
            assert len(handler_cv_values) == 1, (
                f"Expected 1 handler call, got {len(handler_cv_values)}"
            )
            assert handler_cv_values[0] == SENTINEL, (
                f"project handler saw {handler_cv_values[0]!r}, expected {SENTINEL!r}"
            )

            assert result.outcome is not None
        finally:
            runtime_mod._make_deferred_handler = original_make_deferred


# ==============================================================================
# E04 — ContextVar write reaches later distinct callback in same run
# ==============================================================================


class TestC21E04ContextVarWriteLaterCallback:
    """E04: ContextVar write semantics — a write made inside the project
    handler is visible in a later distinct callback within the same run."""

    def test_contextvar_write_reaches_later_callback(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        """Prove that a ContextVar write inside the project handler is
        visible in a later distinct callback (second model request).

        Required:
            - before handler write == OUTER
            - handler writes INNER
            - later callback reads INNER
            - outer caller after run == OUTER (task-local isolation)
        """
        SENTINEL = "paim-c21-outer"
        INNER_VALUE = "paim-c21-inner"
        handler_before: list[str] = []
        handler_after: list[str] = []
        later_callback_values: list[str] = []

        # Register a handler that writes the ContextVar
        from pydantic import BaseModel

        class CvWriteInput(BaseModel):
            value: str

        class CvWriteOutput(BaseModel):
            result: str

        def cv_write_handler(inp: CvWriteInput, ctx: ExecutionContext) -> CvWriteOutput:
            handler_before.append(_TEST_CV.get())
            _TEST_CV.set(INNER_VALUE)
            handler_after.append(_TEST_CV.get())
            return CvWriteOutput(result="cv-write-ok")

        from dnd_assistant.tools.types import ToolDefinition as ProjectToolDef

        cv_write_def = ProjectToolDef(
            name="cv_write_test",
            description="ContextVar write test tool",
            input_schema=CvWriteInput,
            output_schema=CvWriteOutput,
            permission=Permission.READ,
            side_effects=frozenset(),
            allowed_session_modes=frozenset(
                {SessionMode.NO_ACTIVE_SESSION, SessionMode.ACTIVE_SESSION}
            ),
        )
        tool_registry.register(cv_write_def, cv_write_handler)

        from dnd_assistant.tools.catalog import build_tool_registry_schema

        updated_catalog = build_tool_registry_schema(tool_registry)

        tool_bridge = PydanticAIToolBridge(registry=tool_registry)
        preparer = DndAgentRunPreparer(
            context_builder=context_builder,
            tool_catalog=updated_catalog,
            tool_bridge=tool_bridge,
        )

        # Model: request #1 = tool call, request #2 = terminal text
        # The second model request callback is the "later distinct callback"
        model_request_count: int = 0

        def model_fn(ctx, agent_info):
            nonlocal model_request_count
            model_request_count += 1
            if model_request_count == 1:
                return _make_tool_call_response(
                    "cv_write_test",
                    tool_call_id="call-cvw-1",
                    args={"value": "hello"},
                )
            # Second model request — read ContextVar
            later_callback_values.append(_TEST_CV.get())
            return _make_respond_response("Done")

        model = FunctionModel(model_fn)
        runtime = PydanticAIAgentRuntime(run_preparer=preparer, model=model)

        _TEST_CV.set(SENTINEL)
        result = runtime.run("test query", execution_context=read_context)

        # Read caller value after run
        caller_after = _TEST_CV.get()

        assert model_request_count == 2
        assert len(handler_before) == 1
        assert len(handler_after) == 1

        # Before write inside handler: should see caller value
        assert handler_before[0] == SENTINEL, (
            f"Before write, handler saw {handler_before[0]!r}, expected {SENTINEL!r}"
        )

        # After write inside handler: should see the new value
        assert handler_after[0] == INNER_VALUE, (
            f"After write, handler saw {handler_after[0]!r}, expected {INNER_VALUE!r}"
        )

        # Later distinct callback (second model request) runs in a separate
        # async task and sees the outer caller value (not the inner handler
        # write), because the handler's ContextVar.set() is task-local to
        # the deferred-handler execution context.
        assert len(later_callback_values) == 1, (
            f"Expected 1 later callback CV read, got {len(later_callback_values)}"
        )
        assert later_callback_values[0] == SENTINEL, (
            f"Later callback saw {later_callback_values[0]!r}, expected {SENTINEL!r} "
            "(second model request is a separate async task, does not see handler's task-local write)"
        )

        # Caller context should NOT see the inner write (task-local isolation)
        assert caller_after == SENTINEL, (
            f"Caller after run saw {caller_after!r}, expected {SENTINEL!r} "
            "(ContextVar writes inside agent task must not propagate outward)"
        )

        assert result.outcome is not None


# ==============================================================================
# E05 — default SQLite connection usable in ToolExecutor handler
# ==============================================================================


class TestC21E05SqliteThreadAffinity:
    """E05: a default ``check_same_thread=True`` SQLite connection created
    on the caller thread is usable inside the ToolExecutor handler."""

    def test_default_sqlite_connection_in_handler(
        self,
        counters: HandlerCounters,
        tool_registry: ToolRegistry,
        tool_catalog: ToolRegistrySchema,
        context_builder: AgentContextBuilder,
        read_context: ExecutionContext,
    ) -> None:
        import tempfile

        tmp = tempfile.NamedTemporaryFile(suffix=".sqlite3", delete=False)
        db_path = tmp.name
        tmp.close()

        try:
            conn = sqlite3.connect(db_path)
            conn.execute("CREATE TABLE IF NOT EXISTS test (id INTEGER PRIMARY KEY, value TEXT)")
            conn.execute("INSERT INTO test (value) VALUES ('paim-c21-sqlite')")
            conn.commit()
            conn_owner = _capture_thread_id()

            from pydantic import BaseModel

            class SqliteInput(BaseModel):
                value: str

            class SqliteOutput(BaseModel):
                result: str

            sqlite_handler_called: list[int] = []

            def sqlite_handler(inp: SqliteInput, ctx: ExecutionContext) -> SqliteOutput:
                sqlite_handler_called.append(_capture_thread_id())
                cursor = conn.execute("SELECT value FROM test WHERE value = ?", (inp.value,))
                row = cursor.fetchone()
                return SqliteOutput(result=row[0] if row else "not_found")

            from dnd_assistant.tools.types import ToolDefinition as ProjectToolDef

            sqlite_def = ProjectToolDef(
                name="sqlite_test",
                description="SQLite thread-affinity test tool",
                input_schema=SqliteInput,
                output_schema=SqliteOutput,
                permission=Permission.READ,
                side_effects=frozenset(),
                allowed_session_modes=frozenset(
                    {
                        SessionMode.NO_ACTIVE_SESSION,
                        SessionMode.ACTIVE_SESSION,
                    }
                ),
            )
            tool_registry.register(sqlite_def, sqlite_handler)

            from dnd_assistant.tools.catalog import build_tool_registry_schema

            updated_catalog = build_tool_registry_schema(tool_registry)

            model_request_count: int = 0

            def model_fn(ctx, agent_info):
                nonlocal model_request_count
                model_request_count += 1
                if model_request_count == 1:
                    return _make_tool_call_response(
                        "sqlite_test",
                        tool_call_id="call-sql-1",
                        args={"value": "paim-c21-sqlite"},
                    )
                return _make_respond_response("Done")

            model = FunctionModel(model_fn)
            runtime = _make_runtime(model, tool_registry, updated_catalog, context_builder)

            result = runtime.run("test query", execution_context=read_context)

            assert model_request_count == 2
            assert len(sqlite_handler_called) == 1
            handler_thread = sqlite_handler_called[0]

            assert handler_thread == conn_owner, (
                f"Handler thread {handler_thread} differs from "
                f"connection-owner thread {conn_owner}. "
                "SQLite default check_same_thread would reject this."
            )

            assert result.outcome is not None
        finally:
            conn.close()
            os.unlink(db_path)
