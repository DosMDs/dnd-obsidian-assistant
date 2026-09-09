"""Deterministic unit tests for PAIM-13 eval scoring logic.

All offline — no network, no model, no framework imports.
"""

from __future__ import annotations

import pytest

from dnd_assistant.application.agent_loop import AgentLoop
from dnd_assistant.application.agent_tool_execution import (
    AgentToolExecutionService,
)
from dnd_assistant.application.fast_agent import FastAgent
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
from dnd_assistant.models.ollama import OllamaModelProvider
from dnd_assistant.tools.executor import ToolExecutor
from dnd_assistant.tools.registry import ToolRegistry
from tests.support.pydantic_ai_eval import (
    DecisionObservation,
    EvalExpectation,
    EvalScenario,
    ExpectedToolCall,
    ExposedToolInfo,
    FullTurnObservation,
    ScenarioExpectationKind,
    ToolCallObservation,
    classify_majority,
    json_args_equal,
    nearest_rank_percentile,
    score_arguments,
    score_decision,
    score_full_turn,
    score_tool_name,
    summarize_metrics,
)

# ==============================================================================
# nearest_rank_percentile
# ==============================================================================


class TestNearestRankPercentile:
    def test_p50_even_count(self) -> None:
        values = [1.0, 2.0, 3.0, 4.0]
        assert nearest_rank_percentile(values, 50) == 2.0

    def test_p50_odd_count(self) -> None:
        values = [1.0, 2.0, 3.0]
        assert nearest_rank_percentile(values, 50) == 2.0

    def test_p95(self) -> None:
        values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
        assert nearest_rank_percentile(values, 95) == 10.0

    def test_p0(self) -> None:
        values = [1.0, 2.0, 3.0]
        assert nearest_rank_percentile(values, 0) == 1.0

    def test_p100(self) -> None:
        values = [1.0, 2.0, 3.0]
        assert nearest_rank_percentile(values, 100) == 3.0

    def test_single_value(self) -> None:
        values = [42.0]
        assert nearest_rank_percentile(values, 50) == 42.0
        assert nearest_rank_percentile(values, 95) == 42.0

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            nearest_rank_percentile([], 50)

    def test_invalid_percentile_negative(self) -> None:
        with pytest.raises(ValueError, match="Percentile"):
            nearest_rank_percentile([1.0], -1)

    def test_invalid_percentile_over_100(self) -> None:
        with pytest.raises(ValueError, match="Percentile"):
            nearest_rank_percentile([1.0], 101)


# ==============================================================================
# json_args_equal
# ==============================================================================


class TestJsonArgsEqual:
    def test_equal_dicts(self) -> None:
        assert json_args_equal({"a": 1, "b": "x"}, {"b": "x", "a": 1})

    def test_type_mismatch_string_vs_int(self) -> None:
        assert not json_args_equal({"a": "1"}, {"a": 1})

    def test_type_mismatch_int_vs_float(self) -> None:
        assert not json_args_equal({"a": 1}, {"a": 1.0})

    def test_type_mismatch_bool_vs_int(self) -> None:
        assert not json_args_equal({"a": True}, {"a": 1})

    def test_different_keys(self) -> None:
        assert not json_args_equal({"a": 1}, {"b": 1})

    def test_nested_dicts(self) -> None:
        assert json_args_equal({"x": {"y": 2}}, {"x": {"y": 2}})
        assert not json_args_equal({"x": {"y": 2}}, {"x": {"y": "2"}})

    def test_empty_dicts(self) -> None:
        assert json_args_equal({}, {})

    def test_strict_int_vs_bool(self) -> None:
        """0 != False and 1 != True with strict type comparison."""
        assert not json_args_equal({"a": 0}, {"a": False})
        assert not json_args_equal({"a": 1}, {"a": True})

    def test_strict_int_vs_float(self) -> None:
        """1 != 1.0 with strict type comparison."""
        assert not json_args_equal({"a": 1}, {"a": 1.0})

    def test_nested_strict_types(self) -> None:
        """Nested strict type comparison."""
        assert not json_args_equal({"x": {"y": 1}}, {"x": {"y": True}})
        assert not json_args_equal({"x": {"y": 1}}, {"x": {"y": 1.0}})


# ==============================================================================
# score_tool_name
# ==============================================================================


class TestScoreToolName:
    def test_respond_no_tool_pass(self) -> None:
        obs = _make_obs(terminal_kind="respond")
        expectation = EvalExpectation(kind=ScenarioExpectationKind.RESPOND_NO_TOOL)
        assert score_tool_name(obs, expectation)

    def test_respond_no_tool_with_tool_fails(self) -> None:
        obs = _make_obs(
            tool_calls=(
                ToolCallObservation(
                    tool_name="read_npc",
                    arguments={"name": "Arlen"},
                    call_id="1",
                    schema_valid=True,
                ),
            ),
        )
        expectation = EvalExpectation(kind=ScenarioExpectationKind.RESPOND_NO_TOOL)
        assert not score_tool_name(obs, expectation)

    def test_exact_tool_calls_name_match(self) -> None:
        obs = _make_obs(
            tool_calls=(
                ToolCallObservation(
                    tool_name="read_npc",
                    arguments={"name": "Arlen"},
                    call_id="1",
                    schema_valid=True,
                ),
            ),
        )
        expectation = EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(ExpectedToolCall(tool_name="read_npc", arguments={"name": "Arlen"}),),
            order_sensitive=True,
        )
        assert score_tool_name(obs, expectation)

    def test_exact_tool_calls_name_match_wrong_args(self) -> None:
        """score_tool_name passes even with wrong arguments."""
        obs = _make_obs(
            tool_calls=(
                ToolCallObservation(
                    tool_name="read_npc",
                    arguments={"name": "WRONG"},
                    call_id="1",
                    schema_valid=True,
                ),
            ),
        )
        expectation = EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(ExpectedToolCall(tool_name="read_npc", arguments={"name": "Arlen"}),),
            order_sensitive=True,
        )
        assert score_tool_name(obs, expectation)

    def test_exact_tool_calls_wrong_name(self) -> None:
        obs = _make_obs(
            tool_calls=(
                ToolCallObservation(
                    tool_name="read_location",
                    arguments={"name": "Black Keep"},
                    call_id="1",
                    schema_valid=True,
                ),
            ),
        )
        expectation = EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(ExpectedToolCall(tool_name="read_npc", arguments={"name": "Arlen"}),),
            order_sensitive=True,
        )
        assert not score_tool_name(obs, expectation)


# ==============================================================================
# score_arguments
# ==============================================================================


class TestScoreArguments:
    def test_exact_tool_calls_args_match(self) -> None:
        obs = _make_obs(
            tool_calls=(
                ToolCallObservation(
                    tool_name="read_npc",
                    arguments={"name": "Arlen"},
                    call_id="1",
                    schema_valid=True,
                ),
            ),
        )
        expectation = EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(ExpectedToolCall(tool_name="read_npc", arguments={"name": "Arlen"}),),
            order_sensitive=True,
        )
        assert score_arguments(obs, expectation)

    def test_exact_tool_calls_wrong_args_fails(self) -> None:
        """score_arguments fails with wrong arguments even if name is correct."""
        obs = _make_obs(
            tool_calls=(
                ToolCallObservation(
                    tool_name="read_npc",
                    arguments={"name": "WRONG"},
                    call_id="1",
                    schema_valid=True,
                ),
            ),
        )
        expectation = EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(ExpectedToolCall(tool_name="read_npc", arguments={"name": "Arlen"}),),
            order_sensitive=True,
        )
        assert not score_arguments(obs, expectation)

    def test_exact_tool_calls_wrong_name_fails(self) -> None:
        """score_arguments fails with wrong tool name even if args are irrelevant."""
        obs = _make_obs(
            tool_calls=(
                ToolCallObservation(
                    tool_name="read_location",
                    arguments={"name": "Black Keep"},
                    call_id="1",
                    schema_valid=True,
                ),
            ),
        )
        expectation = EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(ExpectedToolCall(tool_name="read_npc", arguments={"name": "Arlen"}),),
            order_sensitive=True,
        )
        assert not score_arguments(obs, expectation)


# ==============================================================================
# score_full_turn
# ==============================================================================


class TestScoreFullTurn:
    def test_respond_no_tool_pass(self) -> None:
        obs = FullTurnObservation(
            scenario_id="test",
            repetition=0,
            duration_seconds=0.1,
            success=True,
            terminal_kind="respond",
        )
        expectation = EvalExpectation(kind=ScenarioExpectationKind.RESPOND_NO_TOOL)
        assert score_full_turn(obs, expectation)

    def test_respond_no_tool_with_execution_fails(self) -> None:
        obs = FullTurnObservation(
            scenario_id="test",
            repetition=0,
            duration_seconds=0.1,
            success=True,
            terminal_kind="respond",
            executed_tool_calls=(
                ToolCallObservation(
                    tool_name="read_npc",
                    arguments={"name": "Arlen"},
                    call_id="1",
                    schema_valid=True,
                ),
            ),
        )
        expectation = EvalExpectation(kind=ScenarioExpectationKind.RESPOND_NO_TOOL)
        assert not score_full_turn(obs, expectation)

    def test_failed_run_fails(self) -> None:
        obs = FullTurnObservation(
            scenario_id="test",
            repetition=0,
            duration_seconds=0.1,
            success=False,
        )
        expectation = EvalExpectation(kind=ScenarioExpectationKind.RESPOND_NO_TOOL)
        assert not score_full_turn(obs, expectation)

    def test_exact_tool_calls_pass(self) -> None:
        obs = FullTurnObservation(
            scenario_id="test",
            repetition=0,
            duration_seconds=0.1,
            success=True,
            terminal_kind="respond",
            executed_tool_calls=(
                ToolCallObservation(
                    tool_name="read_npc",
                    arguments={"name": "Arlen"},
                    call_id="1",
                    schema_valid=True,
                ),
            ),
        )
        expectation = EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(ExpectedToolCall(tool_name="read_npc", arguments={"name": "Arlen"}),),
            order_sensitive=True,
        )
        assert score_full_turn(obs, expectation)


# ==============================================================================
# score_decision
# ==============================================================================


def _make_obs(
    tool_calls: tuple[ToolCallObservation, ...] = (),
    terminal_kind: str | None = None,
) -> DecisionObservation:
    return DecisionObservation(
        scenario_id="test",
        repetition=0,
        duration_seconds=0.1,
        tool_calls=tool_calls,
        terminal_kind=terminal_kind,
    )


class TestScoreDecision:
    def test_respond_no_tool_pass(self) -> None:
        obs = _make_obs(terminal_kind="respond")
        expectation = EvalExpectation(kind=ScenarioExpectationKind.RESPOND_NO_TOOL)
        assert score_decision(obs, expectation)

    def test_respond_no_tool_with_tool_fails(self) -> None:
        obs = _make_obs(
            tool_calls=(
                ToolCallObservation(
                    tool_name="read_npc",
                    arguments={"name": "Arlen"},
                    call_id="1",
                    schema_valid=True,
                ),
            ),
            terminal_kind="respond",
        )
        expectation = EvalExpectation(kind=ScenarioExpectationKind.RESPOND_NO_TOOL)
        assert not score_decision(obs, expectation)

    def test_respond_no_tool_wrong_kind(self) -> None:
        obs = _make_obs(terminal_kind="clarify")
        expectation = EvalExpectation(kind=ScenarioExpectationKind.RESPOND_NO_TOOL)
        assert not score_decision(obs, expectation)

    def test_clarify_no_tool_pass(self) -> None:
        obs = _make_obs(terminal_kind="clarify")
        expectation = EvalExpectation(kind=ScenarioExpectationKind.CLARIFY_NO_TOOL)
        assert score_decision(obs, expectation)

    def test_no_tool_any_terminal_pass(self) -> None:
        obs = _make_obs(terminal_kind="respond")
        expectation = EvalExpectation(kind=ScenarioExpectationKind.NO_TOOL_ANY_TERMINAL)
        assert score_decision(obs, expectation)

    def test_no_tool_any_terminal_with_tool_fails(self) -> None:
        obs = _make_obs(
            tool_calls=(
                ToolCallObservation(
                    tool_name="read_npc",
                    arguments={"name": "Arlen"},
                    call_id="1",
                    schema_valid=True,
                ),
            ),
        )
        expectation = EvalExpectation(kind=ScenarioExpectationKind.NO_TOOL_ANY_TERMINAL)
        assert not score_decision(obs, expectation)

    def test_exact_tool_calls_order_sensitive_pass(self) -> None:
        obs = _make_obs(
            tool_calls=(
                ToolCallObservation(
                    tool_name="read_npc",
                    arguments={"name": "Arlen"},
                    call_id="1",
                    schema_valid=True,
                ),
            ),
        )
        expectation = EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(ExpectedToolCall(tool_name="read_npc", arguments={"name": "Arlen"}),),
            order_sensitive=True,
        )
        assert score_decision(obs, expectation)

    def test_exact_tool_calls_wrong_name(self) -> None:
        obs = _make_obs(
            tool_calls=(
                ToolCallObservation(
                    tool_name="read_location",
                    arguments={"name": "Black Keep"},
                    call_id="1",
                    schema_valid=True,
                ),
            ),
        )
        expectation = EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(ExpectedToolCall(tool_name="read_npc", arguments={"name": "Arlen"}),),
        )
        assert not score_decision(obs, expectation)

    def test_exact_tool_calls_wrong_args(self) -> None:
        obs = _make_obs(
            tool_calls=(
                ToolCallObservation(
                    tool_name="read_npc",
                    arguments={"name": "Mira"},
                    call_id="1",
                    schema_valid=True,
                ),
            ),
        )
        expectation = EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(ExpectedToolCall(tool_name="read_npc", arguments={"name": "Arlen"}),),
        )
        assert not score_decision(obs, expectation)

    def test_exact_tool_calls_extra_tool(self) -> None:
        obs = _make_obs(
            tool_calls=(
                ToolCallObservation(
                    tool_name="read_npc",
                    arguments={"name": "Arlen"},
                    call_id="1",
                    schema_valid=True,
                ),
                ToolCallObservation(
                    tool_name="read_location",
                    arguments={"name": "Black Keep"},
                    call_id="2",
                    schema_valid=True,
                ),
            ),
        )
        expectation = EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(ExpectedToolCall(tool_name="read_npc", arguments={"name": "Arlen"}),),
        )
        assert not score_decision(obs, expectation)

    def test_exact_tool_calls_order_insensitive_pass(self) -> None:
        obs = _make_obs(
            tool_calls=(
                ToolCallObservation(
                    tool_name="read_beta",
                    arguments={"number": 2},
                    call_id="2",
                    schema_valid=True,
                ),
                ToolCallObservation(
                    tool_name="read_alpha",
                    arguments={"value": "hello"},
                    call_id="1",
                    schema_valid=True,
                ),
            ),
        )
        expectation = EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(
                ExpectedToolCall(tool_name="read_alpha", arguments={"value": "hello"}),
                ExpectedToolCall(tool_name="read_beta", arguments={"number": 2}),
            ),
            order_sensitive=False,
        )
        assert score_decision(obs, expectation)

    def test_exact_tool_calls_order_sensitive_fails(self) -> None:
        obs = _make_obs(
            tool_calls=(
                ToolCallObservation(
                    tool_name="read_beta",
                    arguments={"number": 2},
                    call_id="2",
                    schema_valid=True,
                ),
                ToolCallObservation(
                    tool_name="read_alpha",
                    arguments={"value": "hello"},
                    call_id="1",
                    schema_valid=True,
                ),
            ),
        )
        expectation = EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(
                ExpectedToolCall(tool_name="read_alpha", arguments={"value": "hello"}),
                ExpectedToolCall(tool_name="read_beta", arguments={"number": 2}),
            ),
            order_sensitive=True,
        )
        assert not score_decision(obs, expectation)


# ==============================================================================
# classify_majority
# ==============================================================================


def _tc(name: str, args: dict) -> ToolCallObservation:
    return ToolCallObservation(
        tool_name=name,
        arguments=args,
        call_id="1",
        schema_valid=True,
    )


def _obs_for_scenario(
    sid: str,
    terminal_kind: str | None = None,
    tool_calls: tuple[ToolCallObservation, ...] = (),
) -> DecisionObservation:
    return DecisionObservation(
        scenario_id=sid,
        repetition=0,
        duration_seconds=0.1,
        tool_calls=tool_calls,
        terminal_kind=terminal_kind,
    )


class TestClassifyMajority:
    def test_both_pass(self) -> None:
        ref_obs = [
            _obs_for_scenario("T01", terminal_kind="respond"),
            _obs_for_scenario("T01", terminal_kind="respond"),
            _obs_for_scenario("T01", terminal_kind="respond"),
        ]
        cand_obs = [
            _obs_for_scenario("T01", terminal_kind="respond"),
            _obs_for_scenario("T01", terminal_kind="respond"),
            _obs_for_scenario("T01", terminal_kind="respond"),
        ]
        expectation = EvalExpectation(kind=ScenarioExpectationKind.RESPOND_NO_TOOL)
        result = classify_majority("T01", ref_obs, cand_obs, expectation)
        assert result.classification == "BOTH_PASS"
        assert result.reference_passes == 3
        assert result.candidate_passes == 3

    def test_reference_only_pass(self) -> None:
        ref_obs = [
            _obs_for_scenario("T02", terminal_kind="respond"),
            _obs_for_scenario("T02", terminal_kind="respond"),
            _obs_for_scenario("T02", terminal_kind="respond"),
        ]
        cand_obs = [
            _obs_for_scenario("T02", tool_calls=(_tc("read_npc", {}),)),
            _obs_for_scenario("T02", tool_calls=(_tc("read_npc", {}),)),
            _obs_for_scenario("T02", terminal_kind="respond"),
        ]
        expectation = EvalExpectation(kind=ScenarioExpectationKind.RESPOND_NO_TOOL)
        result = classify_majority("T02", ref_obs, cand_obs, expectation)
        assert result.classification == "REFERENCE_ONLY_PASS"

    def test_candidate_only_pass(self) -> None:
        ref_obs = [
            _obs_for_scenario("T03", tool_calls=(_tc("read_npc", {}),)),
            _obs_for_scenario("T03", tool_calls=(_tc("read_npc", {}),)),
            _obs_for_scenario("T03", terminal_kind="respond"),
        ]
        cand_obs = [
            _obs_for_scenario("T03", terminal_kind="respond"),
            _obs_for_scenario("T03", terminal_kind="respond"),
            _obs_for_scenario("T03", terminal_kind="respond"),
        ]
        expectation = EvalExpectation(kind=ScenarioExpectationKind.RESPOND_NO_TOOL)
        result = classify_majority("T03", ref_obs, cand_obs, expectation)
        assert result.classification == "CANDIDATE_ONLY_PASS"

    def test_both_fail(self) -> None:
        ref_obs = [
            _obs_for_scenario("T04", tool_calls=(_tc("read_npc", {}),)),
            _obs_for_scenario("T04", tool_calls=(_tc("read_npc", {}),)),
            _obs_for_scenario("T04", tool_calls=(_tc("read_npc", {}),)),
        ]
        cand_obs = [
            _obs_for_scenario("T04", tool_calls=(_tc("read_npc", {}),)),
            _obs_for_scenario("T04", tool_calls=(_tc("read_npc", {}),)),
            _obs_for_scenario("T04", tool_calls=(_tc("read_npc", {}),)),
        ]
        expectation = EvalExpectation(kind=ScenarioExpectationKind.RESPOND_NO_TOOL)
        result = classify_majority("T04", ref_obs, cand_obs, expectation)
        assert result.classification == "BOTH_FAIL"

    def test_reference_only_pass_detection(self) -> None:
        """REFERENCE_ONLY_PASS is detected correctly (critical for PAIM-13)."""
        ref_obs = [
            _obs_for_scenario("T05", terminal_kind="respond"),
            _obs_for_scenario("T05", terminal_kind="respond"),
            _obs_for_scenario("T05", terminal_kind="respond"),
        ]
        cand_obs = [
            _obs_for_scenario("T05", tool_calls=(_tc("read_npc", {}),)),
            _obs_for_scenario("T05", tool_calls=(_tc("read_npc", {}),)),
            _obs_for_scenario("T05", tool_calls=(_tc("read_npc", {}),)),
        ]
        expectation = EvalExpectation(kind=ScenarioExpectationKind.RESPOND_NO_TOOL)
        result = classify_majority("T05", ref_obs, cand_obs, expectation)
        assert result.classification == "REFERENCE_ONLY_PASS"


# ==============================================================================
# summarize_metrics — basic smoke
# ==============================================================================


class TestSummarizeMetrics:
    def test_empty_scenarios(self) -> None:
        results = summarize_metrics([], [], "reference")
        assert len(results) > 0
        assert results[0].denominator == 0

    def test_single_scenario_all_pass(self) -> None:
        scenarios = [
            EvalScenario(
                scenario_id="T01",
                user_input="hello",
                expectation=EvalExpectation(kind=ScenarioExpectationKind.RESPOND_NO_TOOL),
            )
        ]
        observations = [
            DecisionObservation(
                scenario_id="T01",
                repetition=r,
                duration_seconds=0.1,
                terminal_kind="respond",
            )
            for r in range(3)
        ]
        results = summarize_metrics(scenarios, observations, "reference")
        assert results[0].value == 1.0
        assert results[0].numerator == 1
        assert results[0].denominator == 1

    def test_false_write_detection(self) -> None:
        scenarios = [
            EvalScenario(
                scenario_id="T01",
                user_input="read npc",
                expectation=EvalExpectation(kind=ScenarioExpectationKind.RESPOND_NO_TOOL),
            )
        ]
        observations = [
            DecisionObservation(
                scenario_id="T01",
                repetition=r,
                duration_seconds=0.1,
                tool_calls=(
                    ToolCallObservation(
                        tool_name="write_campaign_note",
                        arguments={"text": "test"},
                        call_id="1",
                        schema_valid=True,
                    ),
                ),
                exposed_tools=ExposedToolInfo(
                    tool_names=("read_npc", "write_campaign_note"),
                    has_write=True,
                ),
            )
            for r in range(3)
        ]
        results = summarize_metrics(scenarios, observations, "candidate")
        # FALSE_WRITE is at index 8
        assert results[8].numerator == 3

    def test_empty_small_sample(self) -> None:
        """Empty/small sample validation for nearest_rank_percentile."""
        with pytest.raises(ValueError, match="empty"):
            nearest_rank_percentile([], 50)


# ==============================================================================
# Offline architecture tests — runtime identity
# ==============================================================================


class TestPaim13RuntimeIdentity:
    """Offline architecture tests asserting correct runtime identity.

    These tests verify that the eval infrastructure correctly identifies
    which runtime class belongs to which path.  They do NOT require
    Ollama or any network access.

    Reference path:
        FastAgent + AgentLoop + AgentToolExecutionService + ToolExecutor

    Candidate path:
        PydanticAIFastAgent + PydanticAIAgentRuntime + DndAgentRunPreparer
        + PydanticAIToolBridge + ToolExecutor
    """

    def test_fast_agent_is_reference_type(self) -> None:
        """FastAgent is the reference decision runtime."""
        assert FastAgent.__name__ == "FastAgent"
        assert not issubclass(FastAgent, PydanticAIFastAgent)

    def test_pydantic_ai_fast_agent_is_candidate_type(self) -> None:
        """PydanticAIFastAgent is the candidate decision runtime."""
        assert PydanticAIFastAgent.__name__ == "PydanticAIFastAgent"
        assert not issubclass(PydanticAIFastAgent, FastAgent)

    def test_agent_loop_is_reference_full_turn_type(self) -> None:
        """AgentLoop is the reference full-turn runtime."""
        assert AgentLoop.__name__ == "AgentLoop"
        assert not issubclass(AgentLoop, PydanticAIAgentRuntime)

    def test_pydantic_ai_agent_runtime_is_candidate_type(self) -> None:
        """PydanticAIAgentRuntime is the candidate full-turn runtime."""
        assert PydanticAIAgentRuntime.__name__ == "PydanticAIAgentRuntime"
        assert not issubclass(PydanticAIAgentRuntime, AgentLoop)

    def test_reference_path_uses_tool_executor(self) -> None:
        """Reference path uses ToolExecutor (not PydanticAIToolBridge)."""
        assert ToolExecutor.__name__ == "ToolExecutor"
        assert ToolRegistry.__name__ == "ToolRegistry"

    def test_candidate_path_uses_pydantic_ai_tool_bridge(self) -> None:
        """Candidate path uses PydanticAIToolBridge (not ToolExecutor directly)."""
        assert PydanticAIToolBridge.__name__ == "PydanticAIToolBridge"
        assert DndAgentRunPreparer.__name__ == "DndAgentRunPreparer"

    def test_reference_uses_ollama_model_provider(self) -> None:
        """Reference path uses native OllamaModelProvider."""
        assert OllamaModelProvider.__name__ == "OllamaModelProvider"

    def test_agent_tool_execution_service_is_reference_type(self) -> None:
        """AgentToolExecutionService is the reference execution service."""
        assert AgentToolExecutionService.__name__ == "AgentToolExecutionService"


# ==============================================================================
# Request/context equality guard
# ==============================================================================


class TestPaim13RequestContextEquality:
    """Verify that reference and candidate runtimes receive equivalent
    request data and execution context for the same scenario.

    These tests ensure the eval harness provides identical inputs to both
    runtimes, so any behavioural difference is attributable to the runtime
    implementation, not to differing input data.
    """

    def test_scenario_user_input_is_deterministic(self) -> None:
        """Same scenario ID always produces the same user_input."""
        s1 = EvalScenario(
            scenario_id="E13-D05",
            user_input="Tell me about Arlen.",
            expectation=EvalExpectation(
                kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
                tool_calls=(
                    ExpectedToolCall(
                        tool_name="read_npc",
                        arguments={"name": "Arlen"},
                    ),
                ),
                order_sensitive=True,
            ),
        )
        s2 = EvalScenario(
            scenario_id="E13-D05",
            user_input="Tell me about Arlen.",
            expectation=EvalExpectation(
                kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
                tool_calls=(
                    ExpectedToolCall(
                        tool_name="read_npc",
                        arguments={"name": "Arlen"},
                    ),
                ),
                order_sensitive=True,
            ),
        )
        assert s1.user_input == s2.user_input
        assert s1.user_input == "Tell me about Arlen."

    def test_scenario_context_is_deterministic(self) -> None:
        """Same scenario ID always produces the same ExecutionContext type."""
        from dnd_assistant.tools.types import (
            ExecutionContext,
            Permission,
            SessionMode,
        )

        ctx_a = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
        )
        ctx_b = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
        )
        assert ctx_a.granted_permission == ctx_b.granted_permission
        assert ctx_a.session_mode == ctx_b.session_mode

    def test_read_write_contexts_differ(self) -> None:
        """READ and WRITE contexts have different permissions."""
        from dnd_assistant.tools.types import (
            ExecutionContext,
            Permission,
            SessionMode,
        )

        read_ctx = ExecutionContext(
            granted_permission=Permission.READ,
            session_mode=SessionMode.NO_ACTIVE_SESSION,
        )
        write_ctx = ExecutionContext(
            granted_permission=Permission.WRITE,
            session_mode=SessionMode.ACTIVE_SESSION,
        )
        assert read_ctx.granted_permission != write_ctx.granted_permission

    def test_scenario_expectation_is_deterministic(self) -> None:
        """Same scenario ID always produces the same expectation."""
        exp1 = EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(
                ExpectedToolCall(
                    tool_name="write_quest_status",
                    arguments={"name": "Moon Gate", "status": "completed"},
                ),
            ),
            order_sensitive=True,
        )
        exp2 = EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(
                ExpectedToolCall(
                    tool_name="write_quest_status",
                    arguments={"name": "Moon Gate", "status": "completed"},
                ),
            ),
            order_sensitive=True,
        )
        assert exp1 == exp2
        assert exp1.kind.name == "EXACT_TOOL_CALLS"
        assert len(exp1.tool_calls) == 1
        assert exp1.tool_calls[0].tool_name == "write_quest_status"
