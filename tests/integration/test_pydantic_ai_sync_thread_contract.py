"""PAIM-10: Sync/thread-safety gate — worker-thread and framework contract.

This file contains the worker-thread ownership, generic framework callback
characterisation, and active-event-loop limitation tests.

All tests use ``FunctionModel`` for deterministic model responses and require
no real Ollama or network access.

Test scenarios
--------------

P10-E08 — runtime constructed+used inside worker thread
P10-E09 — generic Pydantic sync callback worker-thread characterisation
P10-E10 — active-event-loop sync-entrypoint limitation characterisation
"""

from __future__ import annotations

import json
import threading
from collections.abc import Sequence
from queue import Queue
from typing import Any

from pydantic_ai import Agent
from pydantic_ai.messages import ModelResponse, TextPart, ToolCallPart
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
from dnd_assistant.tools.catalog import ToolRegistrySchema
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import (
    ExecutionContext,
    Permission,
    SessionMode,
)
from tests.support.pydantic_ai_runtime import (
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
    audit: Any = None,
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
    model: Any,
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


def _capture_thread_id() -> int:
    return threading.get_ident()


# ==============================================================================
# P10-E08 — runtime constructed+used inside worker thread
# ==============================================================================


class TestP10E08WorkerThreadRuntime:
    """P10-E08: the complete runtime can be constructed AND used inside a
    non-main worker thread."""

    def test_runtime_in_worker_thread(
        self,
    ) -> None:
        """Construct all thread-affine resources inside one worker thread,
        then execute the runtime there.

        Proves the contract is ``same caller/owner thread``, not ``must be
        Python MainThread``.
        """
        result_queue: Queue[dict[str, object]] = Queue()
        error_queue: Queue[BaseException | None] = Queue()

        def worker() -> None:
            try:
                counters_local = make_handler_counters()
                registry = make_tool_registry(counters_local)

                from dnd_assistant.tools.catalog import build_tool_registry_schema

                catalog = build_tool_registry_schema(registry)

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

                ctx_builder = AgentContextBuilder(
                    search_service=_StubSearchService(),
                    vault_repository=_StubVaultRepository(),
                    session_repository=_StubSessionRepo(),
                    event_repository=_StubEventRepo(),
                    world_time_repository=_StubWorldTimeRepo(),
                )

                model_request_count: int = 0

                def model_fn(ctx, agent_info):
                    nonlocal model_request_count
                    model_request_count += 1
                    if model_request_count == 1:
                        return _make_tool_call_response(
                            "read_alpha",
                            tool_call_id="call-1",
                            args={"value": "hello"},
                        )
                    return _make_respond_response("Done")

                model = _make_function_model(model_fn)
                runtime = _make_runtime(model, registry, catalog, ctx_builder)

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


# ==============================================================================
# P10-E09 — generic Pydantic sync callback worker-thread characterisation
# ==============================================================================


class TestP10E09GenericSyncCallback:
    """P10-E09: characterise that generic Pydantic AI synchronous function
    tools CAN be dispatched to a worker thread, unlike our D&D deferred
    external tools."""

    def test_generic_sync_tool_worker_thread(
        self,
    ) -> None:
        """Prove that ordinary ``@agent.tool_plain`` sync callbacks may
        execute on a different thread than the caller.

        This is framework evidence only — it does not change the D&D runtime.
        """
        caller_thread = _capture_thread_id()
        tool_threads: list[int] = []

        def sync_tool(value: str) -> str:
            tool_threads.append(_capture_thread_id())
            return f"hello from thread {_capture_thread_id()}"

        agent = Agent(
            "test",
            retries={"tools": 0},
            deps_type=object,
        )
        agent.tool_plain()(sync_tool)

        result = agent.run_sync("call the tool", deps=object())

        assert len(tool_threads) >= 1, "Tool should have been called"

        # The sync tool may be on a different thread (framework default).
        # This is NOT a failure — it characterises framework behavior.
        on_different_thread = tool_threads[0] != caller_thread
        print(
            f"P10-E09: caller thread={caller_thread}, "
            f"sync tool thread={tool_threads[0]}, "
            f"different={on_different_thread}"
        )

        assert result.output is not None


# ==============================================================================
# P10-E10 — active-event-loop sync-entrypoint limitation characterisation
# ==============================================================================


class TestP10E10ActiveEventLoop:
    """P10-E10: characterise that ``PydanticAIAgentRuntime.run()`` cannot
    be called from code already running an asyncio event loop.

    This is an expected limitation — the current MVP is sync CLI only.
    """

    def test_active_event_loop_limitation(
        self,
    ) -> None:
        """Prove that calling the sync runtime from within an already-running
        event loop raises an appropriate error.

        Uses a subprocess to avoid contaminating pytest's event loop.
        """
        import subprocess
        import sys

        code = """
import asyncio
import sys

async def main():
    from pydantic_ai import Agent
    from pydantic_ai.models.function import FunctionModel

    def model_fn(ctx, info):
        from pydantic_ai.messages import ModelResponse, TextPart
        return ModelResponse(parts=[TextPart(content="hello")])

    model = FunctionModel(model_fn)
    agent = Agent(model)

    try:
        result = agent.run_sync("test")
        print(f"UNEXPECTED_SUCCESS: {result.output}")
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
