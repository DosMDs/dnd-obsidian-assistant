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
from dnd_assistant.evals.datasets.product_v1 import build_product_v1_dataset
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


# ── Product scenario ground-truth ↔ AgentContext correspondence ─────────────
# Ground truth is derived from the real AgentContextBuilder.build() over the
# real synthetic fixture, never from dataset description text.

_DATASET = build_product_v1_dataset()


def _case(scenario_id: str):
    return next(case for case in _DATASET.cases if case.scenario.scenario_id == scenario_id)


def _context(scenario_id: str):
    case = _case(scenario_id)
    fixture = build_fixture(case.execution, model=_model(), scenario_id=scenario_id)
    return fixture, fixture.context_builder.build(case.scenario.user_input)


def test_context_p1_001_current_tick_available() -> None:
    _, context = _context("EVAL-P1-001")
    assert context.current_world_tick == 2100


def test_context_p1_002_both_varos_candidates_visible() -> None:
    _, context = _context("EVAL-P1-002")
    ids = {entity.entity_id for entity in context.relevant_entities}
    assert {"npc-varos-elder", "npc-varos-younger"} <= ids


def test_context_p1_003_kell_truncated_and_tail_fact_absent() -> None:
    _, context = _context("EVAL-P1-003")
    kell = next(
        (entity for entity in context.relevant_entities if entity.entity_id == "npc-kell-001"),
        None,
    )
    assert kell is not None
    assert kell.body_truncated is True
    assert "печать совета" not in kell.body_excerpt


def test_context_p1_004_five_guards_capped_but_handler_sees_all_six() -> None:
    fixture, context = _context("EVAL-P1-004")
    guard_ids = {entity.entity_id for entity in context.relevant_entities}
    assert guard_ids == {f"npc-guard-{index:03d}" for index in range(1, 6)}

    binding = fixture.registry.get("search_entities")
    input_model = binding.definition.input_schema.model_validate(
        {"text": "стража", "entity_types": ["npc"]}
    )
    output = binding.handler(input_model, fixture.execution_context)
    assert len(output.results) == 6  # type: ignore[attr-defined]


def test_context_p1_006_active_session_exposes_only_last_five_events() -> None:
    _, context = _context("EVAL-P1-006")
    assert context.active_session is not None
    assert context.active_session.session_id == "S010"
    event_ids = [event.event_id for event in context.recent_events]
    assert event_ids == [f"evt_{number}" for number in range(103, 108)]


def test_context_p1_008_active_session_id_available() -> None:
    _, context = _context("EVAL-P1-008")
    assert context.active_session is not None
    assert context.active_session.session_id == "S010"
    assert context.recent_events


def test_context_p1_009_ambiguous_write_target_visible() -> None:
    _, context = _context("EVAL-P1-009")
    ids = {entity.entity_id for entity in context.relevant_entities}
    assert {"npc-varos-elder", "npc-varos-younger"} <= ids
