"""Deterministic unit tests for PAIM-13 eval scoring logic.

All offline — no network, no model, no framework imports.
"""

from __future__ import annotations

import pytest

from tests.support.pydantic_ai_eval import (
    DecisionObservation,
    EvalExpectation,
    EvalScenario,
    ExpectedToolCall,
    ExposedToolInfo,
    FullTurnObservation,
    ScenarioExpectationKind,
    ToolCallObservation,
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

    def test_false_write_run_level_counting(self) -> None:
        """False-WRITE numerator counts runs, not individual calls."""
        scenarios = [
            EvalScenario(
                scenario_id="T01",
                user_input="read npc",
                expectation=EvalExpectation(kind=ScenarioExpectationKind.RESPOND_NO_TOOL),
            )
        ]
        # One run emits 2 WRITE calls — should count as 1, not 2
        observations = [
            DecisionObservation(
                scenario_id="T01",
                repetition=0,
                duration_seconds=0.1,
                tool_calls=(
                    ToolCallObservation(
                        tool_name="write_campaign_note",
                        arguments={"text": "a"},
                        call_id="1",
                        schema_valid=True,
                    ),
                    ToolCallObservation(
                        tool_name="write_campaign_note",
                        arguments={"text": "b"},
                        call_id="2",
                        schema_valid=True,
                    ),
                ),
                exposed_tools=ExposedToolInfo(
                    tool_names=("read_npc", "write_campaign_note"), has_write=True
                ),
            ),
            DecisionObservation(
                scenario_id="T01",
                repetition=1,
                duration_seconds=0.1,
                tool_calls=(),
                exposed_tools=ExposedToolInfo(
                    tool_names=("read_npc", "write_campaign_note"), has_write=True
                ),
            ),
        ]
        results = summarize_metrics(scenarios, observations, "candidate")
        # 1 run with WRITE visible and not expected, that run has >=1 WRITE call
        assert results[8].numerator == 1
        assert results[8].denominator == 2

    def test_empty_small_sample(self) -> None:
        """Empty/small sample validation for nearest_rank_percentile."""
        with pytest.raises(ValueError, match="empty"):
            nearest_rank_percentile([], 50)


# ==============================================================================
# Request/context equality guard
# ==============================================================================
# Full harness-drift guards moved to test_pydantic_ai_eval_live_harness.py


# ==============================================================================
# CountingPydanticModel unit tests
# ==============================================================================


class TestCountingPydanticModel:
    """Architecture and basic offline tests for CountingPydanticModel wrapper.

    Comprehensive literal request-counting tests (C29-M02 through C29-M05)
    are in ``test_pydantic_ai_eval_live_harness.py``.
    """

    def test_isinstance_model(self) -> None:
        from pydantic_ai.models import Model as PydanticModel

        from tests.support.paim13_live_harness import CountingPydanticModel

        assert issubclass(CountingPydanticModel, PydanticModel)

    def test_initial_count_is_zero(self) -> None:
        from tests.support.paim13_live_harness import (
            CountingPydanticModel,
            CountingPydanticModelState,
        )
        from tests.support.test_doubles import FakeModel

        counter = CountingPydanticModel(FakeModel())
        assert counter.state.request_count == 0
        assert isinstance(counter.state, CountingPydanticModelState)

    def test_model_name_delegates(self) -> None:
        from tests.support.paim13_live_harness import CountingPydanticModel
        from tests.support.test_doubles import FakeModel

        counter = CountingPydanticModel(FakeModel())
        assert counter.model_name == "fake-model"

    def test_system_delegates(self) -> None:
        from tests.support.paim13_live_harness import CountingPydanticModel
        from tests.support.test_doubles import FakeModel

        counter = CountingPydanticModel(FakeModel())
        assert counter.system == "test-system"


# ==============================================================================
# Deterministic AgentContext builder tests
# ==============================================================================


class TestDeterministicContextBuilder:
    """Offline tests for the deterministic AgentContext builder."""

    def _build(self, query: str):
        from tests.support.paim13_live_harness import make_deterministic_context_builder

        return make_deterministic_context_builder().build(query)

    def test_arlen_query_contains_arlen(self) -> None:
        context = self._build("Tell me about Arlen")
        names = tuple(e.name for e in context.relevant_entities)
        assert "Arlen" in names

    def test_black_keep_query_contains_black_keep(self) -> None:
        context = self._build("What is Black Keep?")
        names = tuple(e.name for e in context.relevant_entities)
        assert "Black Keep" in names

    def test_moon_gate_query_contains_moon_gate(self) -> None:
        context = self._build("Tell me about the Moon Gate quest")
        names = tuple(e.name for e in context.relevant_entities)
        assert "Moon Gate" in names

    def test_greeting_has_no_relevant_entities(self) -> None:
        context = self._build("Hello! How are you?")
        assert len(context.relevant_entities) == 0
