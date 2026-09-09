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
    ScenarioExpectationKind,
    ToolCallObservation,
    classify_majority,
    json_args_equal,
    nearest_rank_percentile,
    score_decision,
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
            )
            for r in range(3)
        ]
        results = summarize_metrics(scenarios, observations, "candidate")
        assert any(r.numerator == 3 for r in results)

    def test_empty_small_sample(self) -> None:
        """Empty/small sample validation for nearest_rank_percentile."""
        with pytest.raises(ValueError, match="empty"):
            nearest_rank_percentile([], 50)
