"""PAIM-C42: Offline evidence for PAIM-13 frozen-observation boundaries.

This module closes two pre-live evidence gaps with deterministic offline
tests (no network, no Ollama, no environment variables):

1. Warm-up model requests are excluded from measured frozen observations.
   The real ``collect_decision_dataset`` / ``collect_full_turn_dataset``
   collectors are exercised with counting fakes, so the assertions cover
   the same collection path the live fixtures use.

2. Frozen scoring / aggregate / report consumers issue zero additional
   semantic model requests.  A literal request counter at the same
   reference (``CountingModelGateway.chat_with_tools``) and candidate
   (``CountingPydanticModel.request``) boundaries is snapshotted before
   and after the consumers run.

The reference ``CountingModelGateway`` literal-counter regression tests
live in ``test_pydantic_ai_eval_model_counters.py``.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any

import pytest

from dnd_assistant.application.agent_loop import AgentLoop
from dnd_assistant.application.agent_tool_execution import (
    AgentToolExecutionService,
)
from dnd_assistant.application.fast_agent import AgentDecision, FastAgent
from dnd_assistant.application.pydantic_ai_agent_runtime import (
    PydanticAIAgentRuntime,
)
from dnd_assistant.application.pydantic_ai_fast_agent import (
    PydanticAIFastAgent,
)
from dnd_assistant.application.pydantic_ai_run_deps import (
    DndAgentRunPreparer,
)
from dnd_assistant.application.pydantic_ai_tool_bridge import (
    PydanticAIToolBridge,
)
from dnd_assistant.models.types import (
    ChatMessage,
    ChatRequest,
    MessageRole,
    ToolAwareResponse,
    ToolCall,
)
from dnd_assistant.tools.catalog import (
    ToolPublicDefinition,
    build_tool_registry_schema,
)
from dnd_assistant.tools.executor import ToolExecutor
from dnd_assistant.tools.types import ExecutionContext, Permission
from tests.integration.test_pydantic_ai_stage9_live_eval_decision import (
    _observe_candidate_decision,
    _observe_reference_decision,
    collect_decision_dataset,
)
from tests.integration.test_pydantic_ai_stage9_live_eval_decision import (
    _warmup as _warmup_decision,
)
from tests.integration.test_pydantic_ai_stage9_live_eval_full_turn import (
    _warmup as _warmup_full_turn,
)
from tests.integration.test_pydantic_ai_stage9_live_eval_full_turn import (
    collect_full_turn_dataset,
)
from tests.support.paim13_live_harness import (
    CountingModelGateway,
    CountingPydanticModel,
    build_eval_registry,
    make_deterministic_context_builder,
)
from tests.support.paim13_scenarios import (
    DECISION_SCENARIOS,
    FULL_TURN_SCENARIOS,
    EvalHandlerState,
    make_read_context,
)
from tests.support.pydantic_ai_eval import (
    DecisionObservation,
    EvalExpectation,
    EvalScenario,
    ScenarioExpectationKind,
    classify_majority,
    count_unauthorized_write_handler_executions,
    nearest_rank_percentile,
    score_full_turn,
    summarize_metrics,
)
from tests.support.pydantic_ai_eval_datasets import (
    FrozenDecisionDataset,
    FrozenFullTurnDataset,
    summarize_full_turn_aggregate,
)
from tests.support.test_doubles import (
    WarmupFakeModel,
    WarmupFakeModelGateway,
)

# ==============================================================================
# Runtime builders (deterministic fakes; mirrors the live fixtures)
# ==============================================================================


class _RecordingWarmupGateway(WarmupFakeModelGateway):
    """Warm-up gateway that records the last user content of each call."""

    def __init__(self) -> None:
        self.contents: list[str | None] = []

    def chat_with_tools(
        self,
        request: ChatRequest,
        tools: list[ToolPublicDefinition],
    ) -> ToolAwareResponse:
        self.contents.append(request.messages[-1].content)
        return super().chat_with_tools(request, tools)


def _build_reference_decision_runtime(
    delegate: Any | None = None,
) -> dict[str, Any]:
    """Build the reference decision runtime with counting fakes."""
    state = EvalHandlerState()
    registry = build_eval_registry(state)
    catalog = build_tool_registry_schema(registry)
    context_builder = make_deterministic_context_builder()

    gateway_delegate = delegate if delegate is not None else WarmupFakeModelGateway()
    counting_gateway = CountingModelGateway(gateway_delegate)
    fast_agent = FastAgent(
        context_builder=context_builder,
        model_gateway=counting_gateway,
        tool_catalog=catalog,
    )
    return {
        "fast_agent": fast_agent,
        "state": state,
        "registry": registry,
        "counting_gateway": counting_gateway,
    }


def _build_candidate_decision_runtime() -> dict[str, Any]:
    """Build the candidate decision runtime with counting fakes."""
    state = EvalHandlerState()
    registry = build_eval_registry(state)
    catalog = build_tool_registry_schema(registry)
    context_builder = make_deterministic_context_builder()

    tool_bridge = PydanticAIToolBridge(registry=registry)
    preparer = DndAgentRunPreparer(
        context_builder=context_builder,
        tool_catalog=catalog,
        tool_bridge=tool_bridge,
    )
    counting_model = CountingPydanticModel(WarmupFakeModel())
    fast_agent = PydanticAIFastAgent(run_preparer=preparer, model=counting_model)
    return {
        "fast_agent": fast_agent,
        "state": state,
        "registry": registry,
        "preparer": preparer,
        "counting_model": counting_model,
    }


def _build_reference_full_turn_runtime(
    delegate: Any | None = None,
) -> dict[str, Any]:
    """Build the reference full-turn runtime with counting fakes."""
    state = EvalHandlerState()
    registry = build_eval_registry(state)
    catalog = build_tool_registry_schema(registry)
    context_builder = make_deterministic_context_builder()

    gateway_delegate = delegate if delegate is not None else WarmupFakeModelGateway()
    counting_gateway = CountingModelGateway(gateway_delegate)
    fast_agent = FastAgent(
        context_builder=context_builder,
        model_gateway=counting_gateway,
        tool_catalog=catalog,
    )
    loop = AgentLoop(
        context_builder=context_builder,
        model_gateway=counting_gateway,
        tool_catalog=catalog,
        tool_execution_service=AgentToolExecutionService(tool_executor=ToolExecutor(registry)),
    )
    return {
        "fast_agent": fast_agent,
        "loop": loop,
        "state": state,
        "registry": registry,
        "counting_gateway": counting_gateway,
    }


def _build_candidate_full_turn_runtime() -> dict[str, Any]:
    """Build the candidate full-turn runtime with counting fakes."""
    state = EvalHandlerState()
    registry = build_eval_registry(state)
    catalog = build_tool_registry_schema(registry)
    context_builder = make_deterministic_context_builder()

    tool_bridge = PydanticAIToolBridge(registry=registry)
    preparer = DndAgentRunPreparer(
        context_builder=context_builder,
        tool_catalog=catalog,
        tool_bridge=tool_bridge,
    )
    counting_model = CountingPydanticModel(WarmupFakeModel())
    fast_agent = PydanticAIFastAgent(run_preparer=preparer, model=counting_model)
    runtime = PydanticAIAgentRuntime(run_preparer=preparer, model=counting_model)
    return {
        "fast_agent": fast_agent,
        "runtime": runtime,
        "state": state,
        "registry": registry,
        "preparer": preparer,
        "counting_model": counting_model,
    }


# ==============================================================================
# Frozen collection fixtures
# ==============================================================================


@dataclass(frozen=True, slots=True)
class DecisionCollection:
    dataset: FrozenDecisionDataset
    reference_gateway: CountingModelGateway
    candidate_model: CountingPydanticModel


@dataclass(frozen=True, slots=True)
class FullTurnCollection:
    dataset: FrozenFullTurnDataset
    reference_gateway: CountingModelGateway
    candidate_model: CountingPydanticModel


@pytest.fixture(scope="module")
def decision_collection() -> DecisionCollection:
    ref_runtime = _build_reference_decision_runtime()
    cand_runtime = _build_candidate_decision_runtime()
    dataset = collect_decision_dataset(ref_runtime, cand_runtime)
    return DecisionCollection(
        dataset=dataset,
        reference_gateway=ref_runtime["counting_gateway"],
        candidate_model=cand_runtime["counting_model"],
    )


@pytest.fixture(scope="module")
def full_turn_collection() -> FullTurnCollection:
    ref_runtime = _build_reference_full_turn_runtime()
    cand_runtime = _build_candidate_full_turn_runtime()
    dataset = collect_full_turn_dataset(ref_runtime, cand_runtime)
    return FullTurnCollection(
        dataset=dataset,
        reference_gateway=ref_runtime["counting_gateway"],
        candidate_model=cand_runtime["counting_model"],
    )


# ==============================================================================
# Gap A — warm-up exclusion
# ==============================================================================


class TestWarmupExclusion:
    """Warm-up model requests must never appear as measured observations."""

    def test_warmup_request_is_counted_exactly_once(self) -> None:
        """One warm-up per runtime increments the semantic counter by 1."""
        ref_runtime = _build_reference_decision_runtime()
        cand_runtime = _build_candidate_decision_runtime()
        ref_gateway: CountingModelGateway = ref_runtime["counting_gateway"]
        cand_model: CountingPydanticModel = cand_runtime["counting_model"]

        assert ref_gateway.state.chat_with_tools_count == 0
        assert cand_model.state.request_count == 0

        _warmup_decision(ref_runtime)
        assert ref_gateway.state.chat_with_tools_count == 1
        assert cand_model.state.request_count == 0

        _warmup_decision(cand_runtime)
        assert cand_model.state.request_count == 1

    def test_full_turn_warmup_request_is_counted_exactly_once(self) -> None:
        """One full-turn warm-up per runtime increments the counter by 1."""
        ref_runtime = _build_reference_full_turn_runtime()
        cand_runtime = _build_candidate_full_turn_runtime()
        ref_gateway: CountingModelGateway = ref_runtime["counting_gateway"]
        cand_model: CountingPydanticModel = cand_runtime["counting_model"]

        assert ref_gateway.state.chat_with_tools_count == 0
        assert cand_model.state.request_count == 0

        _warmup_full_turn(ref_runtime["fast_agent"])
        assert ref_gateway.state.chat_with_tools_count == 1
        assert cand_model.state.request_count == 0

        _warmup_full_turn(cand_runtime["fast_agent"])
        assert cand_model.state.request_count == 1

    def test_decision_warmup_precedes_and_is_distinct_from_measured_requests(self) -> None:
        """Warm-up is the first request; measured requests are scenario inputs."""
        ref_delegate = _RecordingWarmupGateway()
        ref_runtime = _build_reference_decision_runtime(delegate=ref_delegate)
        cand_runtime = _build_candidate_decision_runtime()

        collect_decision_dataset(ref_runtime, cand_runtime)

        measured = len(DECISION_SCENARIOS) * 3
        assert len(ref_delegate.contents) == 1 + measured
        warmup_content = ref_delegate.contents[0]
        assert ref_delegate.contents.count(warmup_content) == 1
        counts = Counter(ref_delegate.contents[1:])
        assert len(counts) == len(DECISION_SCENARIOS)
        assert set(counts.values()) == {3}

    def test_full_turn_warmup_precedes_and_is_distinct_from_measured_requests(self) -> None:
        """Warm-up is the first request; measured requests are scenario inputs."""
        ref_delegate = _RecordingWarmupGateway()
        ref_runtime = _build_reference_full_turn_runtime(delegate=ref_delegate)
        cand_runtime = _build_candidate_full_turn_runtime()

        collect_full_turn_dataset(ref_runtime, cand_runtime)

        measured = len(FULL_TURN_SCENARIOS) * 3
        assert len(ref_delegate.contents) == 1 + measured
        warmup_content = ref_delegate.contents[0]
        assert ref_delegate.contents.count(warmup_content) == 1
        counts = Counter(ref_delegate.contents[1:])
        assert len(counts) == len(FULL_TURN_SCENARIOS)
        assert set(counts.values()) == {3}

    def test_decision_dataset_contains_only_measured_keys(
        self,
        decision_collection: DecisionCollection,
    ) -> None:
        """Warm-up request is separate from the 18x3 measured observations."""
        dataset = decision_collection.dataset

        measured = len(DECISION_SCENARIOS) * 3
        assert len(dataset.reference_observations) == measured
        assert len(dataset.candidate_observations) == measured

        expected_keys = {(s.scenario_id, r) for s in DECISION_SCENARIOS for r in range(3)}
        assert {(o.scenario_id, o.repetition) for o in dataset.reference_observations} == (
            expected_keys
        )
        assert {(o.scenario_id, o.repetition) for o in dataset.candidate_observations} == (
            expected_keys
        )

        # Total semantic requests == 1 warm-up + measured observations.
        assert decision_collection.reference_gateway.state.chat_with_tools_count == 1 + measured
        assert decision_collection.candidate_model.state.request_count == 1 + measured

    def test_full_turn_dataset_contains_only_measured_keys(
        self,
        full_turn_collection: FullTurnCollection,
    ) -> None:
        """Warm-up request is separate from the 9x3 measured observations."""
        dataset = full_turn_collection.dataset

        measured = len(FULL_TURN_SCENARIOS) * 3
        assert len(dataset.reference_observations) == measured
        assert len(dataset.candidate_observations) == measured

        expected_keys = {(s.scenario_id, r) for s in FULL_TURN_SCENARIOS for r in range(3)}
        assert {(o.scenario_id, o.repetition) for o in dataset.reference_observations} == (
            expected_keys
        )
        assert {(o.scenario_id, o.repetition) for o in dataset.candidate_observations} == (
            expected_keys
        )

        measured_requests = sum(o.model_request_count for o in dataset.reference_observations)
        assert full_turn_collection.reference_gateway.state.chat_with_tools_count == (
            1 + measured_requests
        )
        cand_requests = sum(o.model_request_count for o in dataset.candidate_observations)
        assert full_turn_collection.candidate_model.state.request_count == 1 + cand_requests

    def test_frozen_dataset_rejects_extra_warmup_observation(
        self,
        decision_collection: DecisionCollection,
    ) -> None:
        """The frozen DTO structurally rejects a warm-up extra observation."""
        dataset = decision_collection.dataset
        warmup_observation = DecisionObservation(
            scenario_id="__warmup__",
            repetition=0,
            duration_seconds=0.0,
        )

        with pytest.raises(AssertionError):
            FrozenDecisionDataset(
                scenarios=dataset.scenarios,
                reference_observations=(
                    *dataset.reference_observations,
                    warmup_observation,
                ),
                candidate_observations=dataset.candidate_observations,
            )


# ==============================================================================
# Gap B — frozen consumers issue zero additional model requests
# ==============================================================================


class TestFrozenConsumersZeroCalls:
    """Frozen scoring/aggregate/report consumers must not call the model."""

    def test_decision_consumers_issue_zero_model_calls(
        self,
        decision_collection: DecisionCollection,
    ) -> None:
        dataset = decision_collection.dataset
        ref_gateway = decision_collection.reference_gateway
        cand_model = decision_collection.candidate_model

        pre_ref = ref_gateway.state.chat_with_tools_count
        pre_cand = cand_model.state.request_count

        ref_observations = list(dataset.reference_observations)
        cand_observations = list(dataset.candidate_observations)

        ref_metrics = summarize_metrics(DECISION_SCENARIOS, ref_observations, "reference")
        cand_metrics = summarize_metrics(DECISION_SCENARIOS, cand_observations, "candidate")
        for scenario in DECISION_SCENARIOS:
            ref_scenario_obs = [
                o for o in ref_observations if o.scenario_id == scenario.scenario_id
            ]
            cand_scenario_obs = [
                o for o in cand_observations if o.scenario_id == scenario.scenario_id
            ]
            classify_majority(
                scenario.scenario_id, ref_scenario_obs, cand_scenario_obs, scenario.expectation
            )
        nearest_rank_percentile(sorted(o.duration_seconds for o in ref_observations), 50)
        nearest_rank_percentile(sorted(o.duration_seconds for o in cand_observations), 95)

        assert ref_gateway.state.chat_with_tools_count == pre_ref
        assert cand_model.state.request_count == pre_cand

        # Non-vacuous: the consumers actually produced metrics over the scenarios.
        assert len(ref_metrics) == 11
        assert len(cand_metrics) == 11
        assert ref_metrics[0].denominator == len(DECISION_SCENARIOS)

    def test_full_turn_consumers_issue_zero_model_calls(
        self,
        full_turn_collection: FullTurnCollection,
    ) -> None:
        dataset = full_turn_collection.dataset
        ref_gateway = full_turn_collection.reference_gateway
        cand_model = full_turn_collection.candidate_model

        pre_ref = ref_gateway.state.chat_with_tools_count
        pre_cand = cand_model.state.request_count

        ref_observations = list(dataset.reference_observations)
        cand_observations = list(dataset.candidate_observations)

        ref_summary = summarize_full_turn_aggregate(
            list(FULL_TURN_SCENARIOS), ref_observations, "reference"
        )
        cand_summary = summarize_full_turn_aggregate(
            list(FULL_TURN_SCENARIOS), cand_observations, "candidate"
        )

        scenario_map = {s.scenario_id: s for s in FULL_TURN_SCENARIOS}
        for obs in cand_observations:
            score_full_turn(obs, scenario_map[obs.scenario_id].expectation)
            count_unauthorized_write_handler_executions(
                obs, scenario_map[obs.scenario_id].expectation
            )

        assert ref_gateway.state.chat_with_tools_count == pre_ref
        assert cand_model.state.request_count == pre_cand

        # Non-vacuous: the summary aggregates the frozen observations.
        assert ref_summary.total_model_requests == sum(
            o.model_request_count for o in ref_observations
        )
        assert cand_summary.total_model_requests == sum(
            o.model_request_count for o in cand_observations
        )


# ==============================================================================
# Gap C — Layer-A observers read the canonical ToolCall.name field
# ==============================================================================


class _StaticDecisionAgent:
    """Stub decision boundary returning a pre-built ``AgentDecision``.

    Used to exercise the Layer-A observers offline with a real tool call.
    """

    def __init__(self, decision: AgentDecision) -> None:
        self._decision = decision

    def decide(
        self,
        user_input: str,
        *,
        execution_context: ExecutionContext,
    ) -> AgentDecision:
        return self._decision


def _build_tool_call_decision(*, tool_name: str, arguments: dict[str, Any]) -> AgentDecision:
    """Build an ``AgentDecision`` containing exactly one real tool call."""
    exposed = ToolPublicDefinition(
        name=tool_name,
        description="stub tool",
        input_schema={"type": "object"},
        output_schema={"type": "object"},
        permission=Permission.READ,
        side_effects=[],
        allowed_session_modes=[],
    )
    return AgentDecision(
        prompt_version="stub",
        request=ChatRequest(messages=(ChatMessage(role=MessageRole.USER, content="stub request"),)),
        exposed_tools=(exposed,),
        response=ToolAwareResponse(
            message=ChatMessage(
                role=MessageRole.ASSISTANT,
                content=None,
                tool_calls=(ToolCall(name=tool_name, arguments=arguments, call_id="call-1"),),
            )
        ),
    )


class TestToolCallObservationCanonicalField:
    """Both Layer-A observers must read ``ToolCall.name`` (not ``tool_name``)."""

    @pytest.mark.parametrize(
        "observer",
        [_observe_reference_decision, _observe_candidate_decision],
        ids=["reference", "candidate"],
    )
    def test_real_tool_call_is_observed_without_attribute_error(
        self,
        observer: Any,
    ) -> None:
        decision = _build_tool_call_decision(tool_name="read_npc", arguments={"name": "Borin"})
        runtime: dict[str, Any] = {"fast_agent": _StaticDecisionAgent(decision)}
        scenario = EvalScenario(
            scenario_id="E13-OBS",
            user_input="Who is the blacksmith?",
            expectation=EvalExpectation(kind=ScenarioExpectationKind.NO_TOOL_ANY_TERMINAL),
        )

        observation = observer(scenario, 0, runtime, make_read_context())

        # A pre-fix ``tc.tool_name`` AttributeError is swallowed into the
        # observation as an error result — assert the canonical conversion.
        assert observation.error_type is None
        assert observation.error_message is None
        assert len(observation.tool_calls) == 1
        observed = observation.tool_calls[0]
        assert observed.tool_name == "read_npc"
        assert observed.arguments == {"name": "Borin"}
        assert observed.call_id == "call-1"
        assert observed.schema_valid is True
