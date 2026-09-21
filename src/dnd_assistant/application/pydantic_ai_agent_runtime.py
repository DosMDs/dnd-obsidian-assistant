"""Pydantic AI bounded agent runtime (PAIM-08).

This module provides the accepted bounded model-tool-model orchestration.
It performs exactly one Pydantic AI agent run with at most 2 model requests
and at most 4 tool executions.

Architecture
────────────

::

    user input + ExecutionContext
            │
            └── DndAgentRunPreparer.prepare()
                    │
                    └── PreparedDndAgentRun  (deps + exposed_tools)

    PydanticAIAgentRuntime.run(user_input, execution_context=...)
            │
            ├── 1. prepare exactly once
            ├── 2. build_agent_request(prepared.deps.agent_context)
            ├── 3. fresh ExternalToolset from issued snapshot
            ├── 4. fresh HandleDeferredToolCalls (bound to this run)
            ├── 5. one Pydantic AI run (request_limit=2)
            │       ├── request #1: text OR DeferredToolRequests
            │       ├── deferred handler: policy → bridge → build_results
            │       └── request #2: terminal text
            └── 6. map to AgentRunResult

Ownership
─────────

Owned here:
    PydanticAIAgentRuntime — migration bounded-loop runtime.

Owned elsewhere (unchanged):
    DndAgentRunPreparer — preparation orchestration.
    DndAgentPolicy — batch-admission policy.
    PydanticAIToolBridge — snapshot, execution adapter.
    AgentRunResult, AgentDecision, ToolAwareResponse — provider-neutral DTOs.

This module must not import from::
    dnd_assistant.models.gateway
    dnd_assistant.models.ollama
    dnd_assistant.storage
    dnd_assistant.retrieval
    dnd_assistant.cli
    dnd_assistant.tools.executor
"""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from contextvars import ContextVar, Token
from typing import TYPE_CHECKING

from pydantic_ai import Agent, UsageLimits
from pydantic_ai.capabilities import HandleDeferredToolCalls
from pydantic_ai.exceptions import AgentRunError
from pydantic_ai.messages import TextPart, ToolCallPart
from pydantic_ai.models import Model
from pydantic_ai.tools import DeferredToolRequests, DeferredToolResults

from dnd_assistant.application.dnd_agent_policy import MAX_MODEL_REQUESTS_PER_RUN
from dnd_assistant.errors import ModelError, ValidationError
from dnd_assistant.prompts.agent_v3 import PROMPT_VERSION

if TYPE_CHECKING:
    from pydantic_ai import RunContext
    from pydantic_ai.capabilities import AgentCapability
    from pydantic_ai.messages import ModelMessage, ModelResponse
    from pydantic_ai.run import AgentRunResult as PydanticAgentRunResult
    from pydantic_ai.toolsets import AbstractToolset

    from dnd_assistant.application.agent_contracts import (
        AgentDecision,
        AgentRunResult,
        AgentToolExecutionResult,
    )
    from dnd_assistant.application.pydantic_ai_run_deps import (
        DndAgentDeps,
        DndAgentRunPreparer,
        PreparedDndAgentRun,
    )
    from dnd_assistant.models.types import ChatRequest, ToolCall
    from dnd_assistant.tools.types import ExecutionContext


# ── Provider-neutral synchronous re-entry guard ──────────────────────────────
#
# The managed run below delegates to a public asyncio bridge.  Framework
# ``Agent.run_sync()`` fails fast both from an active event loop and from a
# synchronous callback/tool dispatched inside another agent run; the bridge
# must preserve that invariant without importing framework-private guards.
# This module therefore owns a narrow ContextVar set for the whole duration of
# a synchronous run.  The flag is copied into the run task (and into any
# synchronous tool thread the framework dispatches), so a nested synchronous
# invocation fails closed before a second event loop can start.

_IN_PROJECT_SYNC_RUN: ContextVar[bool] = ContextVar(
    "dnd_assistant_pydantic_ai_agent_runtime_in_sync_run",
    default=False,
)

_NESTED_SYNC_RUN_MESSAGE = (
    "PydanticAIAgentRuntime.run() cannot be called from a synchronous callback "
    "or tool executing inside an already-running agent run; make the callback "
    "async and await the agent instead."
)
_ACTIVE_EVENT_LOOP_MESSAGE = (
    "PydanticAIAgentRuntime.run() cannot be called from a running event loop."
)


def _acquire_sync_run_guard() -> Token[bool]:
    """Fail fast on re-entry, then mark the current context as running.

    Raises:
        RuntimeError: If a synchronous project run is already active in this
            context, or if an asyncio event loop is already running.
    """
    if _IN_PROJECT_SYNC_RUN.get():
        raise RuntimeError(_NESTED_SYNC_RUN_MESSAGE)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        pass
    else:
        raise RuntimeError(_ACTIVE_EVENT_LOOP_MESSAGE)

    return _IN_PROJECT_SYNC_RUN.set(True)


class PydanticAIAgentRuntime:
    """Bounded Pydantic AI agent runtime (PAIM-08).

    Performs exactly one Pydantic AI agent run with at most 2 model requests
    and at most ``DndAgentPolicy.MAX_TOOL_CALLS_PER_RUN`` (4) tool executions.

    Args:
        run_preparer: The ``DndAgentRunPreparer`` for context/tool preparation.
        model: A Pydantic AI ``Model`` instance (provider-agnostic).

    Raises:
        TypeError: If ``run_preparer`` is not a ``DndAgentRunPreparer`` or
            ``model`` is not a Pydantic AI ``Model``.
    """

    def __init__(
        self,
        *,
        run_preparer: DndAgentRunPreparer,
        model: Model,
    ) -> None:
        from dnd_assistant.application.pydantic_ai_run_deps import (
            DndAgentRunPreparer as DARP,
        )

        if not isinstance(run_preparer, DARP):
            raise TypeError(
                f"run_preparer must be a DndAgentRunPreparer instance, "
                f"got {type(run_preparer).__name__}"
            )
        if not isinstance(model, Model):
            raise TypeError(
                f"model must be a Pydantic AI Model instance, got {type(model).__name__}"
            )

        self._run_preparer = run_preparer
        self._model = model

    def run(
        self,
        user_input: str,
        *,
        execution_context: ExecutionContext,
    ) -> AgentRunResult:
        """Execute one bounded Pydantic AI agent run.

        Args:
            user_input: The validated user query string.
            execution_context: Trusted Python execution context for tool
                exposure filtering and execution.

        Returns:
            An ``AgentRunResult`` with the decision, tool execution
            results, final response, and terminal outcome.

        Raises:
            ModelError: If the model violates safety policy, framework
                errors occur, or model output is malformed.
            RuntimeError: If called from an already-running event loop or from
                a synchronous callback/tool inside another project agent run.
            ValidationError: Propagated from context builder or tool
                execution.
            NotFoundError: Propagated from tool execution.
            ConflictError: Propagated from tool execution.
            DndAssistantError: Propagated from tool execution.
            Exception: Propagated from tool execution.
        """
        from dnd_assistant.application.agent_contracts import (
            build_agent_request,
        )
        from dnd_assistant.prompts.agent_v3 import SYSTEM_PROMPT

        # 0. Provider-neutral synchronous re-entry guard.  Fails fast on a
        #    nested synchronous run or an already-running event loop, and is
        #    always reset on success or failure.
        guard_token = _acquire_sync_run_guard()
        try:
            # 1. Prepare exactly once (validates input, builds context, selects
            #    tools, issues snapshot, creates fresh policy).
            prepared = self._run_preparer.prepare(
                user_input,
                execution_context=execution_context,
            )

            # 2. Build exact provider-neutral request snapshot
            request = build_agent_request(prepared.deps.agent_context)

            # 3. Fresh ExternalToolset from the issued snapshot
            external_toolset = prepared.deps.tool_bridge.to_external_toolset(
                prepared.deps.tool_snapshot,
            )

            # 4. Fresh HandleDeferredToolCalls bound to this run
            deferred_handler, captured_executions = _make_deferred_handler(prepared)

            # 5. Build framework Agent with:
            #    - instructions = SYSTEM_PROMPT only
            #    - output_type = str | DeferredToolRequests
            #    - retries = 0 (tools and output)
            agent = Agent(
                self._model,
                deps_type=type(prepared.deps),
                instructions=SYSTEM_PROMPT,
                output_type=str | DeferredToolRequests,
                retries={"tools": 0, "output": 0},
            )

            # 6. Perform one bounded Pydantic AI run (max 2 model requests)
            #    through a managed public Agent/Model async context, so
            #    provider-owned HTTP clients are closed deterministically
            #    before this method returns.
            user_payload = request.messages[1].content or ""
            try:
                result = asyncio.run(
                    _run_agent_in_managed_context(
                        agent,
                        user_payload,
                        deps=prepared.deps,
                        toolsets=[external_toolset],
                        capabilities=[deferred_handler],
                        usage_limits=UsageLimits(request_limit=MAX_MODEL_REQUESTS_PER_RUN),
                    )
                )
            except AgentRunError as exc:
                raise ModelError(
                    "Pydantic AI model request failed",
                    cause=exc,
                ) from exc

            # 7. Map framework result to AgentRunResult
            return _map_to_agent_run_result(result, prepared, request, captured_executions)
        finally:
            _IN_PROJECT_SYNC_RUN.reset(guard_token)


async def _run_agent_in_managed_context(
    agent: Agent[DndAgentDeps, str | DeferredToolRequests],
    user_payload: str,
    *,
    deps: DndAgentDeps,
    toolsets: Sequence[AbstractToolset[DndAgentDeps]],
    capabilities: Sequence[AgentCapability[DndAgentDeps]],
    usage_limits: UsageLimits,
) -> PydanticAgentRunResult[str | DeferredToolRequests]:
    """Run one agent inside the public managed Agent/Model async context.

    Entering ``async with agent`` delegates to ``Model.__aenter__`` and then to
    ``Provider.__aenter__``; exiting closes any provider-owned HTTP client.
    This is provider-neutral: ``OllamaModel`` and ``OpenAIChatModel`` follow
    the same public ``Model``/``Provider`` contract.  Request/tool budgets,
    deps, per-run toolset and deferred-tool capability are forwarded unchanged.
    """
    async with agent:
        return await agent.run(
            user_payload,
            deps=deps,
            toolsets=toolsets,
            capabilities=capabilities,
            usage_limits=usage_limits,
            infer_name=False,
        )


# ── Deferred handler factory ──────────────────────────────────────────────────


def _make_deferred_handler(
    prepared: PreparedDndAgentRun,
) -> tuple[
    HandleDeferredToolCalls[DndAgentDeps],
    list[AgentToolExecutionResult],
]:
    """Create a fresh ``HandleDeferredToolCalls`` bound to this run.

    The handler:
    1. Validates ``ctx.deps is prepared.deps`` (exact identity).
    2. Rejects approval requests.
    3. Freezes the complete batch.
    4. Runs ``DndAgentPolicy.admit_tool_batch()`` (full-batch admission
       before any execution).
    5. Converts every admitted call to a provider-neutral project ``ToolCall``
       **before** any ``bridge.execute()``.
    6. Executes each admitted call through ``PydanticAIToolBridge.execute()``
       sequentially.
    7. Returns ``DeferredToolResults`` via ``build_results(calls=...)``.

    Args:
        prepared: The prepared run (carries deps with policy, bridge, snapshot).

    Returns:
        A tuple of ``(HandleDeferredToolCalls, list[AgentToolExecutionResult])``.
    """
    from dnd_assistant.application.agent_contracts import (
        build_agent_tool_execution_result,
    )
    from dnd_assistant.application.pydantic_ai_response_adapter import (
        adapt_pydantic_tool_calls,
    )

    # Closure-scoped mutable state for capturing execution results
    captured_executions: list[AgentToolExecutionResult] = []

    def _handler(
        ctx: RunContext[DndAgentDeps],
        requests: DeferredToolRequests,
    ) -> DeferredToolResults | None:
        # 1. Validate ctx.deps is prepared.deps (exact identity).
        if ctx.deps is not prepared.deps:
            raise ValidationError(
                "Deferred handler received a RunContext bound to a different DndAgentDeps instance"
            )

        deps = ctx.deps

        # 2. Reject approval requests (this project uses external tools only)
        if requests.approvals:
            raise ModelError(
                "Unexpected approval requests in DeferredToolRequests. "
                "This project exposes external tools, not approval tools."
            )

        # 3. Freeze the complete batch once
        calls = tuple(requests.calls)
        if not calls:
            return None

        # 4. Full-batch admission before any execution
        admission = deps.policy.admit_tool_batch(calls)

        # 5. Convert EVERY admitted call to project ToolCall DTOs BEFORE
        #    any bridge.execute().  This is the structural preflight that
        #    rejects non-finite/malformed JSON across the entire batch.
        snapshot_names = deps.tool_snapshot.names
        project_calls = adapt_pydantic_tool_calls(
            tuple(calls[admitted.position] for admitted in admission.calls),
            snapshot_names=snapshot_names,
        )

        # 6. Sequential execution through bridge
        results_by_id: dict[str, str] = {}

        for i, admitted in enumerate(admission.calls):
            # Select the exact original call by position
            call = calls[admitted.position]

            # Internal consistency check
            if call.tool_name != admitted.tool_name:
                raise ModelError(
                    f"Admission position {admitted.position}: tool name mismatch "
                    f"({call.tool_name} vs {admitted.tool_name})"
                )
            if call.tool_call_id != admitted.tool_call_id:
                raise ModelError(
                    f"Admission position {admitted.position}: call ID mismatch "
                    f"({call.tool_call_id} vs {admitted.tool_call_id})"
                )

            # Execute through bridge → ToolExecutor
            output = deps.tool_bridge.execute(
                deps.tool_snapshot,
                call,
                execution_context=deps.execution_context,
            )

            # Build project ToolCall for result recording (use pre-adapted)
            project_call = project_calls[i]

            execution = build_agent_tool_execution_result(project_call, output)
            captured_executions.append(execution)

            # Deterministic TOOL JSON for framework replay
            tool_content = execution.tool_message.content
            assert tool_content is not None  # built by _build_tool_message
            results_by_id[call.tool_call_id] = tool_content

        # 7. Build deferred results using exact call IDs
        try:
            return requests.build_results(calls=results_by_id)
        except ValueError as exc:
            raise ModelError(
                "Failed to bind deferred tool results to the pending tool-call batch",
                cause=exc,
            ) from exc

    return HandleDeferredToolCalls(handler=_handler), captured_executions


# ── Result mapping ────────────────────────────────────────────────────────────


def _map_to_agent_run_result(
    result: PydanticAgentRunResult[str | DeferredToolRequests],
    prepared: PreparedDndAgentRun,
    request: ChatRequest,
    captured_executions: list[AgentToolExecutionResult],
) -> AgentRunResult:
    """Map a Pydantic AI ``AgentRunResult`` to a project ``AgentRunResult``.

    Args:
        result: The framework ``AgentRunResult`` from ``run_sync``.
        prepared: The prepared run (for snapshot/exposure data).
        request: The provider-neutral ``ChatRequest`` (for initial_decision).
        captured_executions: List of ``AgentToolExecutionResult`` from the
            deferred handler.

    Returns:
        A provider-neutral ``AgentRunResult``.

    Raises:
        ModelError: If the result type is unexpected or terminal parsing fails.
    """
    from dnd_assistant.application.agent_contracts import (
        AgentDecision,
        AgentRunResult,
        parse_agent_outcome,
    )
    from dnd_assistant.models.types import (
        ChatMessage,
        MessageRole,
        ToolAwareResponse,
    )

    # Access the public AgentRunResult API
    output = result.output

    # Determine if this was a tool path by checking if any tool calls exist
    # in the message history (first ModelResponse with ToolCallPart).
    has_tool_calls = _has_tool_calls_in_history(result)

    if has_tool_calls:
        # Tool path: build initial decision from first ModelResponse
        initial_decision = _build_initial_decision(result, prepared, request)

        tool_executions = tuple(captured_executions)

        # Build final response from terminal output
        if isinstance(output, str):
            final_response = ToolAwareResponse(
                message=ChatMessage(
                    role=MessageRole.ASSISTANT,
                    content=output,
                    tool_calls=(),
                ),
            )

            outcome = parse_agent_outcome(final_response)

            return AgentRunResult(
                initial_decision=initial_decision,
                tool_executions=tool_executions,
                final_response=final_response,
                outcome=outcome,
            )

        # Framework returned unresolved DeferredToolRequests after handler
        raise ModelError(
            "Framework returned unresolved DeferredToolRequests after "
            "deferred handler. Refusing to return partial result."
        )

    # Direct text-only path: no tool calls in history
    if isinstance(output, str):
        initial_response = ToolAwareResponse(
            message=ChatMessage(
                role=MessageRole.ASSISTANT,
                content=output,
                tool_calls=(),
            ),
        )

        initial_decision = AgentDecision(
            prompt_version=PROMPT_VERSION,
            request=request,
            exposed_tools=prepared.exposed_tools,
            response=initial_response,
        )

        outcome = parse_agent_outcome(initial_response)

        return AgentRunResult(
            initial_decision=initial_decision,
            tool_executions=(),
            final_response=initial_response,
            outcome=outcome,
        )

    raise ModelError(
        f"Unexpected Pydantic AI output type: {type(output).__name__}. "
        "Expected str or DeferredToolRequests."
    )


def _has_tool_calls_in_history(
    result: PydanticAgentRunResult[str | DeferredToolRequests],
) -> bool:
    """Check if the framework run history contains any tool calls.

    Looks for a ``ModelResponse`` with ``ToolCallPart`` in the message history.

    Args:
        result: The framework ``AgentRunResult``.

    Returns:
        ``True`` if any ``ToolCallPart`` is found in the history.
    """
    from pydantic_ai.messages import ModelResponse, ToolCallPart

    all_messages = result.all_messages()
    for msg in all_messages:
        if isinstance(msg, ModelResponse):
            for part in msg.parts:
                if isinstance(part, ToolCallPart):
                    return True
    return False


def _build_initial_decision(
    result: PydanticAgentRunResult[str | DeferredToolRequests],
    prepared: PreparedDndAgentRun,
    request: ChatRequest,
) -> AgentDecision:
    """Build the ``AgentDecision`` from the first model response.

    Args:
        result: The framework ``AgentRunResult``.
        prepared: The prepared run.
        request: The provider-neutral ``ChatRequest``.

    Returns:
        An ``AgentDecision`` representing the first model response.
    """
    from dnd_assistant.application.agent_contracts import AgentDecision
    from dnd_assistant.models.types import (
        ChatMessage,
        MessageRole,
        ToolAwareResponse,
    )

    # Get the first ModelResponse from all_messages
    all_messages = result.all_messages()
    first_response = _find_first_model_response(all_messages)

    if first_response is None:
        raise ModelError("No ModelResponse found in framework run history")

    # Extract text and tool calls from the first response parts
    text_parts: list[str] = []
    tool_call_parts: list[ToolCallPart] = []

    for part in first_response.parts:
        if isinstance(part, TextPart):
            text_parts.append(part.content)
        elif isinstance(part, ToolCallPart):
            tool_call_parts.append(part)

    text_content = " ".join(text_parts) if text_parts else None

    # Adapt tool calls
    adapted_calls = _adapt_tool_calls_from_parts(tool_call_parts, prepared)

    initial_response = ToolAwareResponse(
        message=ChatMessage(
            role=MessageRole.ASSISTANT,
            content=text_content,
            tool_calls=tuple(adapted_calls),
        ),
    )

    return AgentDecision(
        prompt_version=PROMPT_VERSION,
        request=request,
        exposed_tools=prepared.exposed_tools,
        response=initial_response,
    )


def _adapt_tool_calls_from_parts(
    parts: list[ToolCallPart],
    prepared: PreparedDndAgentRun,
) -> list[ToolCall]:
    """Adapt framework ``ToolCallPart`` values to project ``ToolCall`` DTOs.

    Delegates to the shared ``adapt_pydantic_tool_calls()`` helper used by
    both PAIM-07 and PAIM-08.

    Args:
        parts: The framework tool call parts.
        prepared: The prepared run (for snapshot name validation).

    Returns:
        A list of project ``ToolCall`` instances in the original order.

    Raises:
        ModelError: If any tool name is not in the frozen snapshot, or if
            the arguments cannot be represented as a JSON object.
    """
    from dnd_assistant.application.pydantic_ai_response_adapter import (
        adapt_pydantic_tool_calls,
    )

    result = adapt_pydantic_tool_calls(
        parts,
        snapshot_names=prepared.deps.tool_snapshot.names,
    )
    return list(result)


def _find_first_model_response(
    all_messages: list[ModelMessage],
) -> ModelResponse | None:
    """Find the first ``ModelResponse`` in the framework message history.

    Args:
        all_messages: The list returned by ``AgentRunResult.all_messages()``.

    Returns:
        The first ``ModelResponse`` instance, or ``None`` if not found.
    """
    from pydantic_ai.messages import ModelResponse

    for msg in all_messages:
        if isinstance(msg, ModelResponse):
            return msg
    return None


def _get_terminal_output(
    result: PydanticAgentRunResult[str | DeferredToolRequests],
) -> object:
    """Get the terminal output from a Pydantic AI ``AgentRunResult``.

    After the deferred handler resolves, the framework continues the same
    run and the final output should be a ``str`` (terminal text).

    Args:
        result: The framework ``AgentRunResult``.

    Returns:
        The terminal output (expected to be ``str``).
    """
    return result.output
