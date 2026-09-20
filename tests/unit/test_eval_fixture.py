"""Unit tests: synthetic in-memory eval fixture (S14-06)."""

from __future__ import annotations

from pydantic_ai.messages import ModelResponse, TextPart
from pydantic_ai.models.function import AgentInfo, FunctionModel

from dnd_assistant.composition.eval_fixture import (
    InstrumentedToolRegistry,
    build_fixture,
)
from dnd_assistant.errors import NotFoundError
from dnd_assistant.evals.dataset import EvalExecutionSpec, EvalPermission, EvalSessionState
from dnd_assistant.tools.types import Permission

PRODUCTION_TOOL_NAMES = {
    "search_entities",
    "get_entity",
    "patch_entity",
    "append_entity_fact",
    "get_active_session",
    "get_session",
    "list_sessions",
    "list_session_events",
    "start_session",
    "record_event",
    "record_note",
    "end_session",
}


def _model() -> FunctionModel:
    def _respond(_messages: object, _info: AgentInfo) -> ModelResponse:
        return ModelResponse(parts=[TextPart(content="ok")])

    return FunctionModel(_respond)


def _spec(
    permission: EvalPermission = EvalPermission.READ,
    session: EvalSessionState = EvalSessionState.NO_ACTIVE,
) -> EvalExecutionSpec:
    return EvalExecutionSpec(permission, session)


def test_registry_has_exact_production_tool_set() -> None:
    fixture = build_fixture(_spec(), model=_model())
    assert isinstance(fixture.registry, InstrumentedToolRegistry)
    assert len(fixture.registry) == 12
    assert {d.name for d in fixture.registry.list_definitions()} == PRODUCTION_TOOL_NAMES
    assert {tool.name for tool in fixture.catalog.tools} == PRODUCTION_TOOL_NAMES


def test_fresh_state_per_build() -> None:
    spec = _spec(EvalPermission.WRITE, EvalSessionState.ACTIVE)
    first = build_fixture(spec, model=_model())
    second = build_fixture(spec, model=_model())
    assert first.vault_repository is not second.vault_repository
    assert first.execution_context is not second.execution_context


def test_write_does_not_contaminate_other_fixture() -> None:
    spec = _spec(EvalPermission.WRITE, EvalSessionState.NO_ACTIVE)
    first = build_fixture(spec, model=_model())
    second = build_fixture(spec, model=_model())

    binding = first.registry.get("append_entity_fact")
    input_model = binding.definition.input_schema.model_validate(
        {"entity_id": "npc-arlen-001", "expected_revision": 3, "fact": "новый факт"}
    )
    binding.handler(input_model, first.execution_context)

    assert first.vault_repository.get_entity("npc-arlen-001").entity.revision == 4
    assert second.vault_repository.get_entity("npc-arlen-001").entity.revision == 3


def test_handler_instrumentation_records_invocation() -> None:
    fixture = build_fixture(_spec(), model=_model())
    binding = fixture.registry.get("get_entity")
    input_model = binding.definition.input_schema.model_validate({"entity_id": "npc-arlen-001"})
    output = binding.handler(input_model, fixture.execution_context)

    assert output.entity.id == "npc-arlen-001"  # type: ignore[attr-defined]
    assert len(fixture.handler_invocations) == 1
    invocation = fixture.handler_invocations[0]
    assert invocation.tool_name == "get_entity"
    assert invocation.is_write is False
    assert invocation.arguments == {"entity_id": "npc-arlen-001"}


def test_handler_instrumentation_records_write_and_preserves_exception() -> None:
    fixture = build_fixture(_spec(EvalPermission.WRITE), model=_model())
    binding = fixture.registry.get("append_entity_fact")
    input_model = binding.definition.input_schema.model_validate(
        {"entity_id": "missing", "expected_revision": 1, "fact": "x"}
    )
    try:
        binding.handler(input_model, fixture.execution_context)
    except NotFoundError:
        pass
    else:  # pragma: no cover - defensive
        raise AssertionError("expected NotFoundError")
    assert fixture.handler_invocations[-1].is_write is True


def test_deterministic_ids_and_tick() -> None:
    fixture = build_fixture(_spec(), model=_model())
    assert fixture.vault_repository.get_entity("npc-arlen-001").entity.revision == 3
    world = fixture.context_builder
    assert world is not None


def test_write_tool_classified_from_trusted_permission() -> None:
    fixture = build_fixture(_spec(), model=_model())
    assert fixture.registry.get("record_note").definition.permission is Permission.WRITE
    assert fixture.registry.get("get_entity").definition.permission is Permission.READ
