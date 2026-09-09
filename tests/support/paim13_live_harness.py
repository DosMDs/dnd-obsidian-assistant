"""PAIM-13 live eval harness — reusable fixtures, counters, context builders.

This module provides shared infrastructure for the PAIM-13 live eval
comparison tests:

- ``CountingModelGateway`` — wraps native ``ModelGateway`` and counts
  ``chat_with_tools()`` calls (reference-side counting).
- ``CountingPydanticModel`` — wraps Pydantic AI ``Model`` and counts
  ``request()`` calls (candidate-side counting).
- ``_make_deterministic_context_builder()`` — builds an ``AgentContextBuilder``
  with deterministic test doubles.
- ``_build_eval_registry()`` — builds a ``ToolRegistry`` with synthetic
  eval tools.
- ``_build_exposed_info()`` — builds ``ExposedToolInfo`` for a context.
- Deterministic entity data and helper functions.

All offline-safe: no network, no model, no framework imports at module
level.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any

from pydantic_ai.messages import ModelMessage, ModelResponse
from pydantic_ai.models import Model, ModelRequestParameters
from pydantic_ai.settings import ModelSettings

from dnd_assistant.application.agent_context import AgentContextBuilder
from dnd_assistant.application.agent_tool_selection import select_agent_tools
from dnd_assistant.domain.types import Visibility
from dnd_assistant.errors import NotFoundError
from dnd_assistant.models.gateway import ModelGateway
from dnd_assistant.models.types import (
    ChatRequest,
    ToolAwareResponse,
)
from dnd_assistant.retrieval.types import MatchKind, SearchHit
from dnd_assistant.tools.catalog import ToolPublicDefinition, build_tool_registry_schema
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import (
    ExecutionContext,
)
from tests.support.paim13_scenarios import (
    READ_LOCATION_DEF,
    READ_NPC_DEF,
    READ_QUEST_DEF,
    WRITE_CAMPAIGN_NOTE_DEF,
    WRITE_QUEST_STATUS_DEF,
    EvalHandlerState,
    EvalToolOutput,
    ReadLocationInput,
    ReadNpcInput,
    ReadQuestInput,
    WriteCampaignNoteInput,
    WriteQuestStatusInput,
)
from tests.support.pydantic_ai_eval import (
    ExposedToolInfo,
)

# ── Counting ModelGateway decorator (reference side) ──────────────────────────


@dataclass
class CountingGatewayState:
    """Mutable state for a ``CountingModelGateway``.

    Tracks literal ``chat_with_tools`` invocations.
    """

    chat_with_tools_count: int = 0


class CountingModelGateway:
    """Test-only ``ModelGateway`` decorator that counts semantic requests.

    Wraps a real ``ModelGateway`` (``OllamaModelProvider``) and counts
    every ``chat_with_tools()`` call.  Delegates all other calls unchanged.
    """

    def __init__(self, delegate: ModelGateway) -> None:
        self._delegate = delegate
        self._state = CountingGatewayState()

    @property
    def state(self) -> CountingGatewayState:
        return self._state

    def chat_with_tools(
        self,
        request: ChatRequest,
        tools: list[ToolPublicDefinition],
    ) -> ToolAwareResponse:
        self._state.chat_with_tools_count += 1
        return self._delegate.chat_with_tools(request, tools)

    def chat(self, request: ChatRequest) -> ToolAwareResponse:
        return self._delegate.chat(request)

    def generate_structured(self, request: ChatRequest, schema: type) -> Any:
        return self._delegate.generate_structured(request, schema)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return self._delegate.embed(texts)

    def health(self) -> Any:
        return self._delegate.health()


# ── Counting Pydantic Model wrapper (candidate side) ──────────────────────────


@dataclass
class CountingPydanticModelState:
    """Mutable state for a ``CountingPydanticModel``.

    Tracks literal ``request()`` invocations.
    """

    request_count: int = 0


class CountingPydanticModel(Model):
    """Test-only Pydantic AI ``Model`` decorator that counts semantic requests.

    Wraps a real Pydantic AI ``Model`` (e.g. ``OllamaModel``) and counts
    every ``request()`` call.  Delegates ``request_stream()`` and all other
    properties/methods unchanged.

    Usage::

        real_model = build_pydantic_ai_ollama_model(profile)
        counting_model = CountingPydanticModel(real_model)
        agent = PydanticAIFastAgent(..., model=counting_model)
    """

    def __init__(self, delegate: Model) -> None:
        super().__init__()
        self._delegate = delegate
        self._state = CountingPydanticModelState()

    @property
    def state(self) -> CountingPydanticModelState:
        return self._state

    # ── Abstract property delegation ─────────────────────────────────────

    @property
    def model_name(self) -> str:
        return self._delegate.model_name

    @property
    def system(self) -> str:
        return self._delegate.system

    # ── Counted semantic request boundary ────────────────────────────────

    async def request(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
    ) -> ModelResponse:
        """Count the call, then delegate to the wrapped model."""
        self._state.request_count += 1
        return await self._delegate.request(messages, model_settings, model_request_parameters)

    # ── Delegated methods ────────────────────────────────────────────────

    async def request_stream(
        self,
        messages: list[ModelMessage],
        model_settings: ModelSettings | None,
        model_request_parameters: ModelRequestParameters,
        run_context: Any | None = None,
    ) -> AsyncGenerator[Any, None]:
        """Delegate stream request without counting (not used in current eval)."""
        async for chunk in self._delegate.request_stream(
            messages, model_settings, model_request_parameters, run_context
        ):
            yield chunk


# ── Deterministic entity data ─────────────────────────────────────────────────

DETERMINISTIC_ENTITIES: dict[str, dict[str, object]] = {
    "Arlen": {
        "entity_id": "npc-arlen-001",
        "entity_type": "npc",
        "name": "Arlen",
        "status": "active",
        "knowledge_status": "known",
        "tags": ("warrior",),
        "body_excerpt": "Arlen is a brave warrior who protects the village.",
        "body_truncated": False,
    },
    "Mira": {
        "entity_id": "npc-mira-001",
        "entity_type": "npc",
        "name": "Mira",
        "status": "active",
        "knowledge_status": "known",
        "tags": ("mage",),
        "body_excerpt": "Mira is a wise mage who studies ancient magic.",
        "body_truncated": False,
    },
    "Black Keep": {
        "entity_id": "loc-black-keep-001",
        "entity_type": "location",
        "name": "Black Keep",
        "status": "active",
        "knowledge_status": "known",
        "tags": ("fortress",),
        "body_excerpt": "Black Keep is an ancient fortress in the northern mountains.",
        "body_truncated": False,
    },
    "Moon Gate": {
        "entity_id": "quest-moon-gate-001",
        "entity_type": "quest",
        "name": "Moon Gate",
        "status": "active",
        "knowledge_status": "known",
        "tags": ("main",),
        "body_excerpt": "The Moon Gate quest involves finding the lost lunar key.",
        "body_truncated": False,
    },
    "Sunken Bell": {
        "entity_id": "quest-sunken-bell-001",
        "entity_type": "quest",
        "name": "Sunken Bell",
        "status": "active",
        "knowledge_status": "known",
        "tags": ("side",),
        "body_excerpt": "The Sunken Bell quest requires diving into the abyssal trench.",
        "body_truncated": False,
    },
}


def _make_entity_like(data: dict[str, object]) -> Any:
    """Create a simple entity-like object with attribute access."""

    class _EntityLike:
        pass

    obj = _EntityLike()
    obj.id = data["entity_id"]
    obj.type = data["entity_type"]
    obj.name = data["name"]
    obj.status = data["status"]
    obj.visibility = Visibility.PLAYER
    obj.knowledge_status = data["knowledge_status"]
    obj.tags = data["tags"]
    return obj


def _make_document_like(entity: Any, body: str) -> Any:
    """Create a simple document-like object with .entity and .body."""

    class _DocLike:
        pass

    obj = _DocLike()
    obj.entity = entity
    obj.body = body
    return obj


# ── Deterministic context builder ─────────────────────────────────────────────


def make_deterministic_context_builder() -> AgentContextBuilder:
    """Build an ``AgentContextBuilder`` with deterministic test doubles.

    The builder provides 5 entities (Arlen, Mira, Black Keep, Moon Gate,
    Sunken Bell) with stable IDs, status, and body excerpts.  Search
    returns hits matching entity names in user input.  No active session,
    no recent events.  World time raises ``NotFoundError`` (uninitialised).
    """

    class _DeterministicVault:
        def get_entity(self, entity_id: str) -> Any:
            for _key, data in DETERMINISTIC_ENTITIES.items():
                if data["entity_id"] == entity_id:
                    entity = _make_entity_like(data)
                    body = str(data["body_excerpt"])
                    return _make_document_like(entity, body)
            return None

        def read_entity(self, *args: Any, **kwargs: Any) -> Any:
            return None

        def list_entities(self, *args: Any, **kwargs: Any) -> list[Any]:
            return []

        def search_entities(self, *args: Any, **kwargs: Any) -> list[Any]:
            return []

    class _DeterministicSearch:
        def search(self, query: Any, limit: int = 5) -> list[Any]:
            text = query.text.lower() if hasattr(query, "text") else str(query).lower()
            hits: list[Any] = []
            for name, data in DETERMINISTIC_ENTITIES.items():
                if name.lower() in text or text in name.lower():
                    hits.append(
                        SearchHit(
                            entity_id=str(data["entity_id"]),
                            match_kind=MatchKind.EXACT_NAME,
                            score=None,
                        )
                    )
            return hits[:limit]

        def search_entities(self, *args: Any, **kwargs: Any) -> list[Any]:
            return []

    class _NullSessionRepo:
        def get_active_session(self) -> Any:
            return None

    class _NullEventRepo:
        def list_events(self, session_id: str) -> list[Any]:
            return []

    class _NullWorldTimeRepo:
        def get_current_world_time(self) -> Any:
            raise NotFoundError("World time not initialised")

    return AgentContextBuilder(
        vault_repository=_DeterministicVault(),
        search_service=_DeterministicSearch(),
        session_repository=_NullSessionRepo(),
        event_repository=_NullEventRepo(),
        world_time_repository=_NullWorldTimeRepo(),
    )


# ── Tool registry builder ─────────────────────────────────────────────────────


def build_eval_registry(state: EvalHandlerState) -> ToolRegistry:
    """Build a ``ToolRegistry`` with synthetic eval tools and in-memory handlers."""
    registry = ToolRegistry()

    def read_npc_handler(inp: ReadNpcInput, ctx: object) -> EvalToolOutput:
        state.read_npc_calls += 1
        state.all_calls.append("read_npc")
        return EvalToolOutput(result=f"NPC {inp.name}: a brave warrior")

    def read_location_handler(inp: ReadLocationInput, ctx: object) -> EvalToolOutput:
        state.read_location_calls += 1
        state.all_calls.append("read_location")
        return EvalToolOutput(result=f"Location {inp.name}: an ancient fortress")

    def read_quest_handler(inp: ReadQuestInput, ctx: object) -> EvalToolOutput:
        state.read_quest_calls += 1
        state.all_calls.append("read_quest")
        return EvalToolOutput(result=f"Quest {inp.name}: a dangerous journey")

    def write_quest_status_handler(inp: WriteQuestStatusInput, ctx: object) -> EvalToolOutput:
        state.write_quest_status_calls += 1
        state.all_calls.append("write_quest_status")
        return EvalToolOutput(result=f"Quest {inp.name} status updated to {inp.status}")

    def write_campaign_note_handler(inp: WriteCampaignNoteInput, ctx: object) -> EvalToolOutput:
        state.write_campaign_note_calls += 1
        state.all_calls.append("write_campaign_note")
        return EvalToolOutput(result=f"Note saved: {inp.text}")

    registry.register(READ_NPC_DEF, read_npc_handler)
    registry.register(READ_LOCATION_DEF, read_location_handler)
    registry.register(READ_QUEST_DEF, read_quest_handler)
    registry.register(WRITE_QUEST_STATUS_DEF, write_quest_status_handler)
    registry.register(WRITE_CAMPAIGN_NOTE_DEF, write_campaign_note_handler)

    return registry


# ── Exposed tool info helper ──────────────────────────────────────────────────


def build_exposed_info(
    context: ExecutionContext,
    registry: ToolRegistry,
) -> ExposedToolInfo:
    """Build an ``ExposedToolInfo`` for the given context and registry."""
    catalog = build_tool_registry_schema(registry)
    selected = select_agent_tools(catalog, context=context)
    names = tuple(t.name for t in selected)
    has_write = any(t.permission.value == "write" for t in selected)
    return ExposedToolInfo(tool_names=names, has_write=has_write)


# ── Terminal observation parser (shared) ──────────────────────────────────────


def parse_terminal_observation(
    response: Any,
    tool_calls: tuple[Any, ...],
) -> str | None:
    """Parse terminal kind from an ``AgentTextOutcome`` JSON response.

    Returns ``None`` when tool calls are present (not terminal).
    Returns the outcome kind value string when a valid outcome is parsed.
    Sets ``error_type`` on the caller when parsing fails (never returns
    ``"clarify"`` for malformed data).

    Args:
        response: The ``ToolAwareResponse`` from a decision.
        tool_calls: Observed tool calls (non-empty means not terminal).

    Returns:
        The terminal kind string, or ``None`` if tool calls exist.
    """
    if tool_calls:
        return None

    from dnd_assistant.application.agent_loop import _parse_agent_outcome
    from dnd_assistant.errors import ModelError

    try:
        outcome = _parse_agent_outcome(response)
        return outcome.kind.value
    except (ModelError, Exception):
        # Malformed terminal — caller must set error_type
        return None
