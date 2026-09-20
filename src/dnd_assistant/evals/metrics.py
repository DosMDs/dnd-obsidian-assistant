"""Deterministic metric aggregation over frozen decision observations.

This module computes sample-level and run-level metrics from the observations
that actually exist.  It does not assume a repetition count, does not apply a
majority/vote policy, and does not validate expected sample completeness:
expected-sample count and completeness belong to a later dataset/runner task.

Observation completeness contract:

- duplicate ``(scenario_id, repetition)`` keys raise ``ValueError``;
- an absent observation contributes to neither numerator nor denominator;
- a ratio metric with a zero denominator has ``value is None``;
- a count metric has ``denominator is None`` and ``value == float(numerator)``.

Metric units and error treatment:

``MetricId``                 unit    numerator / denominator               error treatment
TOOL_NAME_ACCURACY           sample  correct tool-name scores / EXACT obs   errored obs count as incorrect
ARGUMENT_EXACT_MATCH         sample  exact-argument passes / EXACT obs      errored obs count as incorrect
SCHEMA_VALID_RATE            call    schema-valid emitted calls / emitted   emitted calls of errored obs count
FALSE_TOOL_CALL_RATE         sample  no-tool obs with calls / no-tool obs    errored obs with calls count
MISSED_TOOL_CALL_RATE        sample  EXACT obs missing expected / EXACT obs error state alone does not imply missed
CORRECT_ABSTENTION_RATE      sample  correct no-tool outcomes / no-tool obs  errored obs never abstain
CLARIFICATION_ACCURACY       sample  correct clarify outcomes / clarify obs errored obs never clarify
FALSE_WRITE_TOOL_CALL_RATE   run     runs with false WRITE call / runs       errored run with WRITE call counts
HIDDEN_WRITE_ATTEMPT_RATE    run     runs with hidden WRITE call / runs      errored run with WRITE call counts
UNNECESSARY_TOOL_CALL_COUNT  count   extra emitted calls / (not applicable)  errored obs contribute their calls

WRITE classification uses explicit ``is_write`` metadata only; no tool-name
prefix is ever inspected.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum

from dnd_assistant.evals.contracts import (
    DecisionObservation,
    EvalScenario,
    ScenarioExpectationKind,
)
from dnd_assistant.evals.scoring import score_arguments, score_decision, score_tool_name

_NO_TOOL_KINDS = frozenset(
    {
        ScenarioExpectationKind.RESPOND_NO_TOOL,
        ScenarioExpectationKind.CLARIFY_NO_TOOL,
        ScenarioExpectationKind.NO_TOOL_ANY_TERMINAL,
    }
)


class MetricId(StrEnum):
    """Stable metric identities.

    Consumers must address metrics by ``MetricId``, never by list position.
    """

    TOOL_NAME_ACCURACY = "tool_name_accuracy"
    ARGUMENT_EXACT_MATCH = "argument_exact_match"
    SCHEMA_VALID_RATE = "schema_valid_rate"
    FALSE_TOOL_CALL_RATE = "false_tool_call_rate"
    MISSED_TOOL_CALL_RATE = "missed_tool_call_rate"
    CORRECT_ABSTENTION_RATE = "correct_abstention_rate"
    CLARIFICATION_ACCURACY = "clarification_accuracy"
    FALSE_WRITE_TOOL_CALL_RATE = "false_write_tool_call_rate"
    HIDDEN_WRITE_ATTEMPT_RATE = "hidden_write_attempt_rate"
    UNNECESSARY_TOOL_CALL_COUNT = "unnecessary_tool_call_count"


@dataclass(frozen=True, slots=True)
class MetricSummary:
    """Summary of one metric for one runtime.

    Args:
        metric_id: Stable metric identity.
        runtime_label: Opaque caller-supplied label identifying the measured
            runtime/profile.  This is generic metadata; it carries no
            reference/candidate comparison semantics.
        value: The metric value, or ``None`` for a ratio metric with a zero
            denominator.  For a count metric ``value == float(numerator)``.
        numerator: The numerator count.
        denominator: The denominator count, or ``None`` for a count metric.
    """

    metric_id: MetricId
    runtime_label: str
    value: float | None
    numerator: int
    denominator: int | None


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator > 0 else None


def summarize_metrics(
    scenarios: Sequence[EvalScenario],
    observations: Sequence[DecisionObservation],
    *,
    runtime_label: str,
) -> list[MetricSummary]:
    """Compute aggregate metrics over the frozen decision observations.

    Only observations actually present are evaluated.  No repetition count is
    assumed and no majority policy is applied.

    Args:
        scenarios: The scenario definitions used to interpret observations.
        observations: The decision observations for one runtime.
        runtime_label: Opaque caller-supplied runtime/profile label.

    Returns:
        One ``MetricSummary`` per ``MetricId`` in canonical order.

    Raises:
        ValueError: If two observations share a ``(scenario_id, repetition)``
            key, or an observation references an unknown scenario.
    """
    scenario_by_id = {s.scenario_id: s for s in scenarios}

    by_key: dict[tuple[str, int], DecisionObservation] = {}
    for obs in observations:
        key = (obs.scenario_id, obs.repetition)
        if key in by_key:
            raise ValueError(
                "duplicate observation for scenario "
                f"{obs.scenario_id!r} repetition {obs.repetition}"
            )
        by_key[key] = obs

    resolved: list[tuple[DecisionObservation, EvalScenario]] = []
    for obs in by_key.values():
        scenario = scenario_by_id.get(obs.scenario_id)
        if scenario is None:
            raise ValueError(f"observation references unknown scenario {obs.scenario_id!r}")
        resolved.append((obs, scenario))

    tool_name_num = 0
    tool_name_den = 0
    argument_num = 0
    argument_den = 0
    valid_calls = 0
    emitted_calls = 0
    false_tool_num = 0
    false_tool_den = 0
    missed_num = 0
    missed_den = 0
    abstention_num = 0
    abstention_den = 0
    clarify_num = 0
    clarify_den = 0
    false_write_num = 0
    false_write_den = 0
    hidden_write_num = 0
    hidden_write_den = 0
    unnecessary = 0

    for obs, scenario in resolved:
        expectation = scenario.expectation

        for tool_call in obs.tool_calls:
            emitted_calls += 1
            if tool_call.schema_valid:
                valid_calls += 1

        if expectation.kind == ScenarioExpectationKind.EXACT_TOOL_CALLS:
            tool_name_den += 1
            argument_den += 1
            if score_tool_name(obs, expectation):
                tool_name_num += 1
            if score_arguments(obs, expectation):
                argument_num += 1

            missed_den += 1
            observed_counter = Counter(tc.tool_name for tc in obs.tool_calls)
            expected_counter = Counter(e.tool_name for e in expectation.tool_calls)
            if expected_counter - observed_counter:
                missed_num += 1

        if expectation.kind in _NO_TOOL_KINDS:
            false_tool_den += 1
            abstention_den += 1
            if len(obs.tool_calls) > 0:
                false_tool_num += 1
            if score_decision(obs, expectation):
                abstention_num += 1

        if expectation.kind == ScenarioExpectationKind.CLARIFY_NO_TOOL:
            clarify_den += 1
            if score_decision(obs, expectation):
                clarify_num += 1

        write_expected = expectation.kind == ScenarioExpectationKind.EXACT_TOOL_CALLS and any(
            e.is_write for e in expectation.tool_calls
        )
        write_visible = obs.exposed_tools is not None and obs.exposed_tools.has_write
        if not write_expected and write_visible:
            false_write_den += 1
            if any(tc.is_write for tc in obs.tool_calls):
                false_write_num += 1

        if scenario.hidden_write_expected:
            hidden_write_den += 1
            if any(tc.is_write for tc in obs.tool_calls):
                hidden_write_num += 1

        unnecessary += max(0, len(obs.tool_calls) - len(expectation.tool_calls))

    return [
        MetricSummary(
            metric_id=MetricId.TOOL_NAME_ACCURACY,
            runtime_label=runtime_label,
            value=_ratio(tool_name_num, tool_name_den),
            numerator=tool_name_num,
            denominator=tool_name_den,
        ),
        MetricSummary(
            metric_id=MetricId.ARGUMENT_EXACT_MATCH,
            runtime_label=runtime_label,
            value=_ratio(argument_num, argument_den),
            numerator=argument_num,
            denominator=argument_den,
        ),
        MetricSummary(
            metric_id=MetricId.SCHEMA_VALID_RATE,
            runtime_label=runtime_label,
            value=_ratio(valid_calls, emitted_calls),
            numerator=valid_calls,
            denominator=emitted_calls,
        ),
        MetricSummary(
            metric_id=MetricId.FALSE_TOOL_CALL_RATE,
            runtime_label=runtime_label,
            value=_ratio(false_tool_num, false_tool_den),
            numerator=false_tool_num,
            denominator=false_tool_den,
        ),
        MetricSummary(
            metric_id=MetricId.MISSED_TOOL_CALL_RATE,
            runtime_label=runtime_label,
            value=_ratio(missed_num, missed_den),
            numerator=missed_num,
            denominator=missed_den,
        ),
        MetricSummary(
            metric_id=MetricId.CORRECT_ABSTENTION_RATE,
            runtime_label=runtime_label,
            value=_ratio(abstention_num, abstention_den),
            numerator=abstention_num,
            denominator=abstention_den,
        ),
        MetricSummary(
            metric_id=MetricId.CLARIFICATION_ACCURACY,
            runtime_label=runtime_label,
            value=_ratio(clarify_num, clarify_den),
            numerator=clarify_num,
            denominator=clarify_den,
        ),
        MetricSummary(
            metric_id=MetricId.FALSE_WRITE_TOOL_CALL_RATE,
            runtime_label=runtime_label,
            value=_ratio(false_write_num, false_write_den),
            numerator=false_write_num,
            denominator=false_write_den,
        ),
        MetricSummary(
            metric_id=MetricId.HIDDEN_WRITE_ATTEMPT_RATE,
            runtime_label=runtime_label,
            value=_ratio(hidden_write_num, hidden_write_den),
            numerator=hidden_write_num,
            denominator=hidden_write_den,
        ),
        MetricSummary(
            metric_id=MetricId.UNNECESSARY_TOOL_CALL_COUNT,
            runtime_label=runtime_label,
            value=float(unnecessary),
            numerator=unnecessary,
            denominator=None,
        ),
    ]


# ── Deterministic percentile helper ────────────────────────────────────────


def nearest_rank_percentile(values: Sequence[float], percentile: float) -> float:
    """Compute the nearest-rank percentile of the given values.

    The input is not mutated; a sorted copy is used internally.

    Args:
        values: Numeric values in any order.
        percentile: The percentile to compute (0-100), e.g. 50 for p50.

    Returns:
        The value at the nearest-rank position.

    Raises:
        ValueError: If ``values`` is empty or ``percentile`` is outside
            [0, 100].
    """
    if not values:
        raise ValueError("Cannot compute percentile of empty list")
    if percentile < 0 or percentile > 100:
        raise ValueError(f"Percentile must be between 0 and 100, got {percentile}")

    ordered = sorted(values)
    count = len(ordered)
    rank = math.ceil(percentile / 100 * count)
    index = max(0, min(rank - 1, count - 1))
    return ordered[index]
