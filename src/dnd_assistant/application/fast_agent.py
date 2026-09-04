"""One-step Fast Agent decision boundary (S9-02).

This module owns only:

- one-step Fast Agent orchestration
- deterministic model-request construction
- one ``chat_with_tools`` invocation
- turn-local tool allowlist validation
- provider-neutral decision snapshot

It must not own:

- ToolExecutor execution
- handler invocation
- tool argument schema execution
- tool-result conversion / replay
- multi-round loop
- retry policy
- clarification classification
- CLI
- Vault access
- retrieval
- calendar arithmetic
- Ollama transport

Importing this module must NOT eagerly load::

    dnd_assistant.models.ollama
    dnd_assistant.tools.executor
    dnd_assistant.storage
    dnd_assistant.retrieval
    dnd_assistant.cli
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING

from dnd_assistant.errors import ModelError
from dnd_assistant.prompts.agent_v2 import PROMPT_VERSION, SYSTEM_PROMPT

if TYPE_CHECKING:
    from dnd_assistant.application.agent_context import AgentContext, AgentContextBuilder
    from dnd_assistant.models.gateway import ModelGateway
    from dnd_assistant.models.types import ChatRequest, ToolAwareResponse
    from dnd_assistant.tools.catalog import ToolPublicDefinition, ToolRegistrySchema
    from dnd_assistant.tools.types import ExecutionContext


# ── Public DTO ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class AgentDecision:
    """Provider-neutral snapshot of a single Fast Agent decision step.

    Attributes:
        prompt_version: Reproducible prompt identity for tracing/evals.
        request: Exact conversation history used for the first model turn.
        exposed_tools: Exact allowlist snapshot shown to the model for this turn.
        response: Validated provider-neutral ``ToolAwareResponse``.
    """

    prompt_version: str
    request: ChatRequest
    exposed_tools: tuple[ToolPublicDefinition, ...]
    response: ToolAwareResponse


# ── FastAgent ───────────────────────────────────────────────────────────────────


class FastAgent:
    """One-step Fast Agent orchestration.

    The ``decide()`` method performs exactly one model decision step:
    tool selection → context building → one ``chat_with_tools`` call →
    tool-name allowlist validation → ``AgentDecision``.
    """

    def __init__(
        self,
        *,
        context_builder: AgentContextBuilder,
        model_gateway: ModelGateway,
        tool_catalog: ToolRegistrySchema,
    ) -> None:
        self._context_builder = context_builder
        self._model_gateway = model_gateway
        self._tool_catalog = tool_catalog

    def decide(
        self,
        user_input: str,
        *,
        execution_context: ExecutionContext,
    ) -> AgentDecision:
        """Perform exactly one model decision step.

        Args:
            user_input: The validated user query string.
            execution_context: Trusted Python execution context for tool
                exposure filtering.

        Returns:
            An ``AgentDecision`` snapshot.

        Raises:
            ModelError: If the model response contains tool calls that
                reference tools not in the turn-local exposure snapshot,
                or if the underlying ``chat_with_tools`` call fails.
        """
        # Deferred runtime imports: keep provider/tool/storage packages out
        # of module-import scope.
        from dnd_assistant.application.agent_tool_selection import select_agent_tools
        from dnd_assistant.models.types import ChatMessage, ChatRequest, MessageRole

        # 1. Determine the turn-local exposed-tool snapshot
        exposed_list = select_agent_tools(
            self._tool_catalog,
            context=execution_context,
        )
        exposed_tools = tuple(exposed_list)

        # 2. Build AgentContext
        context = self._context_builder.build(user_input)

        # 3. Build deterministic ChatRequest
        user_payload = _build_user_json(context)
        request = ChatRequest(
            messages=(
                ChatMessage(role=MessageRole.SYSTEM, content=SYSTEM_PROMPT),
                ChatMessage(role=MessageRole.USER, content=user_payload),
            ),
        )

        # 4. Call ModelGateway.chat_with_tools() exactly once
        response = self._model_gateway.chat_with_tools(request, exposed_list)

        # 5. Validate all returned ToolCall names against the exact
        #    exposed-tool snapshot
        for call in response.message.tool_calls:
            if not any(call.name == t.name for t in exposed_tools):
                raise ModelError(
                    f"Tool call '{call.name}' is not in the exposed-tool allowlist for this turn"
                )

        # 6. Return AgentDecision
        return AgentDecision(
            prompt_version=PROMPT_VERSION,
            request=request,
            exposed_tools=exposed_tools,
            response=response,
        )


# ── Deterministic USER JSON payload ────────────────────────────────────────────


def _build_user_json(context: AgentContext) -> str:
    """Build a deterministic JSON string from an ``AgentContext``.

    The payload uses explicit field mapping so that future fields added to
    ``AgentContext`` do not automatically leak into model context.
    """
    payload: dict[str, object] = {
        "user_input": context.user_input,
        "current_world_tick": context.current_world_tick,
        "active_session": _serialize_session(context.active_session),
        "relevant_entities": [_serialize_entity(e) for e in context.relevant_entities],
        "recent_events": [_serialize_event(e) for e in context.recent_events],
    }
    return json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _serialize_session(
    session: object,
) -> dict[str, object] | None:
    """Serialize an ``AgentSessionContext`` or return ``None``."""
    if session is None:
        return None
    # Avoid circular import: AgentSessionContext is a frozen dataclass
    return {
        "session_id": session.session_id,
        "world_tick_start": session.world_tick_start,
    }


def _serialize_entity(entity: object) -> dict[str, object]:
    """Serialize an ``AgentEntityContext``."""
    return {
        "entity_id": entity.entity_id,
        "entity_type": entity.entity_type,
        "name": entity.name,
        "status": entity.status,
        "knowledge_status": entity.knowledge_status,
        "tags": list(entity.tags),
        "body_excerpt": entity.body_excerpt,
        "body_truncated": entity.body_truncated,
    }


def _serialize_event(event: object) -> dict[str, object]:
    """Serialize an ``AgentEventContext``."""
    return {
        "event_id": event.event_id,
        "event_type": event.event_type,
        "world_tick": event.world_tick,
        "text_excerpt": event.text_excerpt,
        "text_truncated": event.text_truncated,
    }
