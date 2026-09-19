"""Deterministic tests for the provider-neutral eval metric contract.

All offline: stdlib and ``dnd_assistant.evals`` only, no network, no model.
"""

from __future__ import annotations

import pytest

from dnd_assistant.evals import (
    DecisionObservation,
    EvalExpectation,
    EvalScenario,
    ExpectedToolCall,
    ExposedToolInfo,
    MetricId,
    MetricSummary,
    ScenarioExpectationKind,
    ToolCallObservation,
    summarize_metrics,
)

_EXPECTED_IDS = {
    MetricId.TOOL_NAME_ACCURACY,
    MetricId.ARGUMENT_EXACT_MATCH,
    MetricId.SCHEMA_VALID_RATE,
    MetricId.FALSE_TOOL_CALL_RATE,
    MetricId.MISSED_TOOL_CALL_RATE,
    MetricId.CORRECT_ABSTENTION_RATE,
    MetricId.CLARIFICATION_ACCURACY,
    MetricId.FALSE_WRITE_TOOL_CALL_RATE,
    MetricId.HIDDEN_WRITE_ATTEMPT_RATE,
    MetricId.UNNECESSARY_TOOL_CALL_COUNT,
}


def _tc(
    tool_name: str,
    arguments: dict[str, object] | None = None,
    *,
    schema_valid: bool = True,
    is_write: bool = False,
) -> ToolCallObservation:
    return ToolCallObservation(
        tool_name=tool_name,
        arguments=arguments if arguments is not None else {},
        call_id="1",
        schema_valid=schema_valid,
        is_write=is_write,
    )


def _obs(
    scenario_id: str,
    *,
    repetition: int = 0,
    tool_calls: tuple[ToolCallObservation, ...] = (),
    terminal_kind: str | None = None,
    exposed: ExposedToolInfo | None = None,
    error_type: str | None = None,
) -> DecisionObservation:
    return DecisionObservation(
        scenario_id=scenario_id,
        repetition=repetition,
        duration_seconds=0.1,
        tool_calls=tool_calls,
        terminal_kind=terminal_kind,
        exposed_tools=exposed,
        error_type=error_type,
    )


def _respond(scenario_id: str = "T01") -> EvalScenario:
    return EvalScenario(
        scenario_id=scenario_id,
        user_input="hello",
        expectation=EvalExpectation(kind=ScenarioExpectationKind.RESPOND_NO_TOOL),
    )


def _no_tool_any(scenario_id: str, *, hidden: bool = False) -> EvalScenario:
    return EvalScenario(
        scenario_id=scenario_id,
        user_input="do something",
        expectation=EvalExpectation(kind=ScenarioExpectationKind.NO_TOOL_ANY_TERMINAL),
        hidden_write_expected=hidden,
    )


def _exact(
    scenario_id: str, *calls: ExpectedToolCall, order_sensitive: bool = True
) -> EvalScenario:
    return EvalScenario(
        scenario_id=scenario_id,
        user_input="read",
        expectation=EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=tuple(calls),
            order_sensitive=order_sensitive,
        ),
    )


def _by_id(summaries: list[MetricSummary]) -> dict[MetricId, MetricSummary]:
    return {m.metric_id: m for m in summaries}


def _summary(
    metric_id: MetricId,
    scenarios: list[EvalScenario],
    obs: list[DecisionObservation],
) -> MetricSummary:
    return _by_id(summarize_metrics(scenarios, obs, runtime_label="run-a"))[metric_id]


class TestMetricIdentityAndUnits:
    def test_all_metric_ids_present_and_unique(self) -> None:
        summaries = summarize_metrics([], [], runtime_label="run-a")
        ids = [m.metric_id for m in summaries]
        assert len(ids) == len(set(ids))
        assert set(ids) == _EXPECTED_IDS

    def test_no_scenario_success_or_majority_metric(self) -> None:
        ids = {m.metric_id for m in summarize_metrics([], [], runtime_label="run-a")}
        assert not any("scenario" in m.value or "majority" in m.value for m in ids)

    def test_runtime_label_is_opaque(self) -> None:
        summaries = summarize_metrics([], [], runtime_label="ollama/qwen-2.5-7b")
        assert all(m.runtime_label == "ollama/qwen-2.5-7b" for m in summaries)

    def test_summarize_metrics_takes_label_keyword_only(self) -> None:
        with pytest.raises(TypeError):
            summarize_metrics([], [], "run-a")  # type: ignore[misc]

    def test_ratio_metric_zero_denominator_is_none(self) -> None:
        summaries = _by_id(summarize_metrics([], [], runtime_label="run-a"))
        for metric_id in _EXPECTED_IDS - {MetricId.UNNECESSARY_TOOL_CALL_COUNT}:
            metric = summaries[metric_id]
            assert metric.denominator == 0, metric_id
            assert metric.value is None, metric_id

    def test_count_metric_has_none_denominator(self) -> None:
        metric = _summary(MetricId.UNNECESSARY_TOOL_CALL_COUNT, [], [])
        assert metric.denominator is None
        assert metric.value == 0.0
        assert metric.numerator == 0

    def test_count_metric_value_equals_numerator(self) -> None:
        scenario = _respond()
        obs = [
            _obs("T01", repetition=rep, tool_calls=(_tc("read_npc"), _tc("read_quest")))
            for rep in range(3)
        ]
        metric = _summary(MetricId.UNNECESSARY_TOOL_CALL_COUNT, [scenario], obs)
        assert metric.numerator == 6
        assert metric.value == 6.0
        assert metric.denominator is None


class TestObservationCompleteness:
    def test_denominator_derived_from_present_observations(self) -> None:
        scenario = _respond()
        obs = [_obs("T01", repetition=rep, terminal_kind="respond") for rep in (0, 2, 7)]
        metric = _summary(MetricId.CORRECT_ABSTENTION_RATE, [scenario], obs)
        assert metric.denominator == 3
        assert metric.numerator == 3

    def test_absent_observation_not_counted_as_success(self) -> None:
        scenario = _respond()
        obs = [_obs("T01", repetition=0, terminal_kind="respond")]
        metric = _summary(MetricId.CORRECT_ABSTENTION_RATE, [scenario], obs)
        assert metric.denominator == 1
        assert metric.value == 1.0

    def test_absent_observation_not_counted_as_abstention_or_valid(self) -> None:
        scenario = _respond()
        metric = _summary(MetricId.CORRECT_ABSTENTION_RATE, [scenario], [])
        assert metric.numerator == 0
        assert metric.denominator == 0
        assert metric.value is None

    def test_duplicate_observation_raises(self) -> None:
        scenario = _respond()
        obs = [
            _obs("T01", repetition=0, terminal_kind="respond"),
            _obs("T01", repetition=0, terminal_kind="respond"),
        ]
        with pytest.raises(ValueError, match="duplicate observation"):
            summarize_metrics([scenario], obs, runtime_label="run-a")

    def test_unknown_scenario_raises(self) -> None:
        with pytest.raises(ValueError, match="unknown scenario"):
            summarize_metrics([], [_obs("NOPE")], runtime_label="run-a")


class TestCorrectAbstention:
    def test_respond_abstention(self) -> None:
        scenario = _respond()
        metric = _summary(
            MetricId.CORRECT_ABSTENTION_RATE,
            [scenario],
            [_obs("T01", terminal_kind="respond")],
        )
        assert metric.numerator == 1

    def test_wrong_terminal_is_not_abstention(self) -> None:
        scenario = _respond()
        metric = _summary(
            MetricId.CORRECT_ABSTENTION_RATE,
            [scenario],
            [_obs("T01", terminal_kind="clarify")],
        )
        assert metric.numerator == 0

    def test_no_tool_any_terminal_requires_real_terminal(self) -> None:
        scenario = _no_tool_any("T01")
        assert (
            _summary(
                MetricId.CORRECT_ABSTENTION_RATE,
                [scenario],
                [_obs("T01", terminal_kind="respond")],
            ).numerator
            == 1
        )
        assert (
            _summary(
                MetricId.CORRECT_ABSTENTION_RATE,
                [scenario],
                [_obs("T01", terminal_kind=None)],
            ).numerator
            == 0
        )

    def test_errored_observation_never_abstains(self) -> None:
        scenario = _respond()
        metric = _summary(
            MetricId.CORRECT_ABSTENTION_RATE,
            [scenario],
            [_obs("T01", terminal_kind="respond", error_type="ModelError")],
        )
        assert metric.numerator == 0
        assert metric.denominator == 1


class TestClarification:
    def _clarify(self) -> EvalScenario:
        return EvalScenario(
            scenario_id="T01",
            user_input="which npc?",
            expectation=EvalExpectation(kind=ScenarioExpectationKind.CLARIFY_NO_TOOL),
        )

    def test_clarify_pass(self) -> None:
        metric = _summary(
            MetricId.CLARIFICATION_ACCURACY,
            [self._clarify()],
            [_obs("T01", terminal_kind="clarify")],
        )
        assert metric.value == 1.0

    def test_errored_never_clarifies(self) -> None:
        metric = _summary(
            MetricId.CLARIFICATION_ACCURACY,
            [self._clarify()],
            [_obs("T01", terminal_kind="clarify", error_type="ModelError")],
        )
        assert metric.numerator == 0


class TestFalseAndMissedToolCalls:
    def test_false_tool_call_counts_call_on_no_tool_scenario(self) -> None:
        scenario = _respond()
        metric = _summary(
            MetricId.FALSE_TOOL_CALL_RATE,
            [scenario],
            [
                _obs("T01", tool_calls=(_tc("read_npc"),)),
                _obs("T01", repetition=1, terminal_kind="respond"),
            ],
        )
        assert metric.numerator == 1
        assert metric.denominator == 2

    def test_errored_with_call_counts_as_false_tool_call(self) -> None:
        metric = _summary(
            MetricId.FALSE_TOOL_CALL_RATE,
            [_respond()],
            [_obs("T01", tool_calls=(_tc("read_npc"),), error_type="ModelError")],
        )
        assert metric.numerator == 1

    def test_missed_tool_call(self) -> None:
        scenario = _exact(
            "T01", ExpectedToolCall(tool_name="read_npc", arguments={"name": "Arlen"})
        )
        metric = _summary(
            MetricId.MISSED_TOOL_CALL_RATE,
            [scenario],
            [_obs("T01")],
        )
        assert metric.numerator == 1
        assert metric.denominator == 1

    def test_not_missed_when_expected_present(self) -> None:
        scenario = _exact(
            "T01", ExpectedToolCall(tool_name="read_npc", arguments={"name": "Arlen"})
        )
        metric = _summary(
            MetricId.MISSED_TOOL_CALL_RATE,
            [scenario],
            [_obs("T01", tool_calls=(_tc("read_npc", {"name": "Arlen"}),))],
        )
        assert metric.numerator == 0

    def test_missed_uses_multiset_not_set(self) -> None:
        scenario = _exact(
            "T01",
            ExpectedToolCall(tool_name="read_npc", arguments={"name": "Arlen"}),
            ExpectedToolCall(tool_name="read_npc", arguments={"name": "Mira"}),
            order_sensitive=False,
        )
        metric = _summary(
            MetricId.MISSED_TOOL_CALL_RATE,
            [scenario],
            [_obs("T01", tool_calls=(_tc("read_npc", {"name": "Arlen"}),))],
        )
        assert metric.numerator == 1


class TestSchemaValid:
    def test_numerator_denominator_over_emitted_calls(self) -> None:
        metric = _summary(
            MetricId.SCHEMA_VALID_RATE,
            [_exact("T01", ExpectedToolCall(tool_name="a", arguments={}))],
            [
                _obs(
                    "T01",
                    tool_calls=(
                        _tc("a", schema_valid=True),
                        _tc("a", schema_valid=False),
                    ),
                )
            ],
        )
        assert metric.numerator == 1
        assert metric.denominator == 2
        assert metric.value == 0.5

    def test_errored_observation_emitted_calls_still_count(self) -> None:
        metric = _summary(
            MetricId.SCHEMA_VALID_RATE,
            [_respond()],
            [
                _obs(
                    "T01",
                    tool_calls=(_tc("read_npc", schema_valid=True),),
                    error_type="ModelError",
                )
            ],
        )
        assert metric.numerator == 1
        assert metric.denominator == 1

    def test_zero_emitted_calls_is_none(self) -> None:
        metric = _summary(
            MetricId.SCHEMA_VALID_RATE,
            [_respond()],
            [_obs("T01", terminal_kind="respond")],
        )
        assert metric.denominator == 0
        assert metric.value is None


class TestWriteClassification:
    def test_write_classification_uses_is_write_not_name_prefix(self) -> None:
        scenario = _respond()
        exposed = ExposedToolInfo(tool_names=("read_npc", "write_like_read"), has_write=True)
        observations = [
            # A READ tool whose name starts with "write_" must not count.
            _obs(
                "T01",
                tool_calls=(_tc("write_like_read", is_write=False),),
                terminal_kind="respond",
                exposed=exposed,
            ),
            # A WRITE tool whose name does not start with "write_" must count.
            _obs(
                "T01",
                repetition=1,
                tool_calls=(_tc("apply_effect", is_write=True),),
                terminal_kind="respond",
                exposed=exposed,
            ),
        ]
        metric = _summary(MetricId.FALSE_WRITE_TOOL_CALL_RATE, [scenario], observations)
        assert metric.numerator == 1
        assert metric.denominator == 2

    def test_expected_write_scenario_not_in_false_write_denominator(self) -> None:
        scenario = _exact(
            "T01",
            ExpectedToolCall(tool_name="apply_effect", arguments={"v": 1}, is_write=True),
        )
        metric = _summary(
            MetricId.FALSE_WRITE_TOOL_CALL_RATE,
            [scenario],
            [
                _obs(
                    "T01",
                    tool_calls=(_tc("apply_effect", {"v": 1}, is_write=True),),
                    exposed=ExposedToolInfo(tool_names=("apply_effect",), has_write=True),
                )
            ],
        )
        assert metric.denominator == 0
        assert metric.value is None

    def test_hidden_write_attempt_uses_is_write(self) -> None:
        scenario = _no_tool_any("T01", hidden=True)
        metric = _summary(
            MetricId.HIDDEN_WRITE_ATTEMPT_RATE,
            [scenario],
            [
                _obs("T01", tool_calls=(_tc("apply_effect", is_write=True),)),
                _obs("T01", repetition=1, tool_calls=(_tc("read_npc", is_write=False),)),
            ],
        )
        assert metric.numerator == 1
        assert metric.denominator == 2
