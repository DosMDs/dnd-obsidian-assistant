"""PAIM-13 eval scoring — deterministic DTOs and helpers.

This module defines only test/eval DTOs and deterministic scoring logic.
No production imports that create network activity at import time.
No global mutable eval state.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

# ── Terminal outcome kinds ─────────────────────────────────────────────────────


class EvalTerminalKind(StrEnum):
    """Expected terminal outcome for a decision scenario."""

    RESPOND = "respond"
    CLARIFY = "clarify"
    RESPOND_NO_TOOL = "respond_no_tool"
    CLARIFY_NO_TOOL = "clarify_no_tool"
    NO_TOOL_ANY_TERMINAL = "no_tool_any_terminal"


class ScenarioExpectationKind(StrEnum):
    """Expected action kind for a decision scenario."""

    RESPOND_NO_TOOL = "respond_no_tool"
    CLARIFY_NO_TOOL = "clarify_no_tool"
    EXACT_TOOL_CALLS = "exact_tool_calls"
    NO_TOOL_ANY_TERMINAL = "no_tool_any_terminal"


# ── Scenario definition ────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ExpectedToolCall:
    """Expected exact tool call in a decision scenario.

    Args:
        tool_name: Exact expected tool name.
        arguments: Exact expected JSON-serialisable arguments dict.
    """

    tool_name: str
    arguments: dict[str, Any]


@dataclass(frozen=True, slots=True)
class EvalExpectation:
    """Deterministic expectation for one decision scenario.

    Args:
        kind: The expected action kind.
        tool_calls: Expected tool calls (for EXACT_TOOL_CALLS).
        order_sensitive: Whether tool-call order matters.
            ``False`` means the multiset must match.
    """

    kind: ScenarioExpectationKind
    tool_calls: tuple[ExpectedToolCall, ...] = ()
    order_sensitive: bool = True


@dataclass(frozen=True, slots=True)
class EvalScenario:
    """One deterministic eval scenario.

    Args:
        scenario_id: Human-readable unique scenario ID (e.g. "E13-D01").
        user_input: The user query string.
        expectation: The expected outcome.
        description: Human-readable description of the scenario.
        hidden_write_expected: Whether WRITE tools are expected to be
            hidden/unexposed for this scenario.  When ``True``, WRITE
            tools are not visible to the model.  This is an explicit
            flag, not derived from description text.
    """

    scenario_id: str
    user_input: str
    expectation: EvalExpectation
    description: str = ""
    hidden_write_expected: bool = False


# ── Exposed tool info ──────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ExposedToolInfo:
    """Snapshot of which tools were visible to the model for a turn.

    Args:
        tool_names: Tuple of exposed tool names in exposure order.
        has_write: Whether any exposed tool has WRITE permission.
    """

    tool_names: tuple[str, ...]
    has_write: bool


# ── Observation DTOs ───────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ToolCallObservation:
    """Observed tool call from a model decision.

    Args:
        tool_name: The tool name emitted by the model.
        arguments: The raw arguments dict (may be malformed).
        call_id: The tool call ID if available.
        schema_valid: Whether the arguments pass schema validation.
    """

    tool_name: str
    arguments: dict[str, Any]
    call_id: str | None
    schema_valid: bool


@dataclass(frozen=True, slots=True)
class DecisionObservation:
    """Observation of one model decision step.

    Args:
        scenario_id: The scenario ID this observation belongs to.
        repetition: The repetition number (0-indexed).
        duration_seconds: Wall-clock duration of the decision.
        tool_calls: Observed tool calls (empty if none).
        terminal_kind: Observed terminal kind.
        terminal_content: The assistant text content (may be None).
        exposed_tools: Snapshot of tools visible to the model for this turn.
        error_type: Error type string if an exception occurred, else None.
        error_message: Error message if an exception occurred, else None.
    """

    scenario_id: str
    repetition: int
    duration_seconds: float
    tool_calls: tuple[ToolCallObservation, ...] = ()
    terminal_kind: str | None = None
    terminal_content: str | None = None
    exposed_tools: ExposedToolInfo | None = None
    error_type: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class FullTurnObservation:
    """Observation of one full-turn runtime execution.

    Args:
        scenario_id: The scenario ID this observation belongs to.
        repetition: The repetition number (0-indexed).
        duration_seconds: Wall-clock duration of the full turn.
        success: Whether the turn completed without error.
        terminal_kind: The terminal outcome kind (RESPOND/CLARIFY).
        initial_tool_calls: The exact tool calls emitted in the first
            model response, with names and arguments.
        executed_tool_calls: The exact tool calls that were actually
            executed, with names and arguments.
        tool_call_count: Number of initial tool calls emitted.
        tool_execution_count: Number of tool executions performed.
        model_request_count: Number of semantic model requests.
        handler_call_count: Total number of handler invocations.
        write_handler_count: Number of WRITE handler invocations.
        exposed_tools: Snapshot of tools visible to the model for this turn.
        error_type: Error type string if an exception occurred, else None.
        error_message: Error message if an exception occurred, else None.
    """

    scenario_id: str
    repetition: int
    duration_seconds: float
    success: bool
    terminal_kind: str | None = None
    initial_tool_calls: tuple[ToolCallObservation, ...] = ()
    executed_tool_calls: tuple[ToolCallObservation, ...] = ()
    tool_call_count: int = 0
    tool_execution_count: int = 0
    model_request_count: int = 0
    handler_call_count: int = 0
    write_handler_count: int = 0
    exposed_tools: ExposedToolInfo | None = None
    error_type: str | None = None
    error_message: str | None = None


# ── Metric summaries ───────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class MetricSummary:
    """Summary of one metric for one runtime.

    Args:
        runtime_label: "reference" or "candidate".
        value: The metric value (e.g. 0.95 for 95%).
        numerator: The numerator count.
        denominator: The denominator count.
    """

    runtime_label: str
    value: float
    numerator: int
    denominator: int


@dataclass(frozen=True, slots=True)
class ScenarioComparison:
    """Comparison result for one scenario across both runtimes.

    Args:
        scenario_id: The scenario ID.
        reference_passes: Number of reference passes (0-3).
        candidate_passes: Number of candidate passes (0-3).
        classification: The majority classification.
    """

    scenario_id: str
    reference_passes: int
    candidate_passes: int
    classification: Literal[
        "BOTH_PASS",
        "REFERENCE_ONLY_PASS",
        "CANDIDATE_ONLY_PASS",
        "BOTH_FAIL",
    ]


# ── Deterministic percentile helper ────────────────────────────────────────────


def nearest_rank_percentile(
    sorted_values: list[float],
    percentile: float,
) -> float:
    """Compute the nearest-rank percentile.

    Args:
        sorted_values: Sorted list of values (ascending).
        percentile: The percentile to compute (0-100), e.g. 50 for p50.

    Returns:
        The value at the nearest-rank position.

    Raises:
        ValueError: If ``sorted_values`` is empty or ``percentile`` is
            outside [0, 100].
    """
    if not sorted_values:
        raise ValueError("Cannot compute percentile of empty list")
    if percentile < 0 or percentile > 100:
        raise ValueError(f"Percentile must be between 0 and 100, got {percentile}")

    n = len(sorted_values)
    rank = math.ceil(percentile / 100 * n)
    index = max(0, min(rank - 1, n - 1))
    return sorted_values[index]


# ── Deterministic JSON argument comparison ─────────────────────────────────────


def json_args_equal(left: dict[str, Any], right: dict[str, Any]) -> bool:
    """Compare two argument dicts using strict recursive type comparison.

    Preserves exact JSON structural types:
    - ``0 != False``, ``1 != True``, ``1 != 1.0``
    - ``None`` matches only ``None``
    - ``bool`` matches only ``bool``
    - ``int`` matches only ``int``
    - ``float`` matches only ``float``
    - ``str`` matches only ``str``
    - ``list`` order matters
    - ``dict`` key order does NOT matter

    This is the same semantics as the production ``_json_args_equal``
    in ``agent_tool_execution.py``.
    """
    return _strict_json_value_equal(left, right)


def _strict_json_value_equal(left: object, right: object) -> bool:
    """Recursive strict JSON value comparison preserving exact types."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        if len(left) != len(right):
            return False
        for k in left:
            if k not in right:
                return False
            if not _strict_json_value_equal(left[k], right[k]):
                return False
        return True
    if isinstance(left, list):
        if len(left) != len(right):
            return False
        return all(_strict_json_value_equal(a, b) for a, b in zip(left, right, strict=True))
    return left == right


# ── Decision scoring ───────────────────────────────────────────────────────────


def score_tool_name(
    observation: DecisionObservation,
    expectation: EvalExpectation,
) -> bool:
    """Score tool-name accuracy only (names/count/order), ignoring arguments.

    Returns ``True`` if the observed tool names, count, and order match
    the expectation.  Argument content is NOT evaluated.

    An errored observation (``error_type is not None``) always returns
    ``False``.

    Args:
        observation: The observed decision.
        expectation: The expected outcome.

    Returns:
        ``True`` if tool names match, ``False`` otherwise.
    """
    # An errored observation cannot pass
    if observation.error_type is not None:
        return False

    observed_tools = observation.tool_calls
    observed_names = tuple(t.tool_name for t in observed_tools)

    if expectation.kind == ScenarioExpectationKind.NO_TOOL_ANY_TERMINAL:
        return len(observed_tools) == 0

    if expectation.kind in (
        ScenarioExpectationKind.RESPOND_NO_TOOL,
        ScenarioExpectationKind.CLARIFY_NO_TOOL,
    ):
        return len(observed_tools) == 0

    if expectation.kind == ScenarioExpectationKind.EXACT_TOOL_CALLS:
        expected = expectation.tool_calls
        expected_names = tuple(e.tool_name for e in expected)

        if len(observed_names) != len(expected_names):
            return False

        if expectation.order_sensitive:
            return observed_names == expected_names
        else:
            return set(observed_names) == set(expected_names)

    return False


def score_arguments(
    observation: DecisionObservation,
    expectation: EvalExpectation,
) -> bool:
    """Score argument exact match only (tool names must also be correct).

    Returns ``True`` only if:
    - Tool names/count/order match the expectation.
    - Every observed tool call's arguments match exactly.

    Args:
        observation: The observed decision.
        expectation: The expected outcome.

    Returns:
        ``True`` if tool names AND arguments match exactly.
    """
    # First check tool names pass
    if not score_tool_name(observation, expectation):
        return False

    if expectation.kind != ScenarioExpectationKind.EXACT_TOOL_CALLS:
        return True

    observed_tools = observation.tool_calls
    expected = expectation.tool_calls

    if expectation.order_sensitive:
        for obs, exp in zip(observed_tools, expected, strict=True):
            if not json_args_equal(obs.arguments, exp.arguments):
                return False
    else:
        observed_by_name: dict[str, list[dict[str, Any]]] = {}
        for obs in observed_tools:
            observed_by_name.setdefault(obs.tool_name, []).append(obs.arguments)

        expected_by_name: dict[str, list[dict[str, Any]]] = {}
        for exp in expected:
            expected_by_name.setdefault(exp.tool_name, []).append(exp.arguments)

        if set(observed_by_name) != set(expected_by_name):
            return False

        for name in observed_by_name:
            obs_args_list = observed_by_name[name]
            exp_args_list = expected_by_name[name]
            if len(obs_args_list) != len(exp_args_list):
                return False
            # Sort by deterministic JSON for multiset comparison
            obs_sorted = sorted(
                obs_args_list,
                key=lambda a: json.dumps(a, sort_keys=True, ensure_ascii=False),
            )
            exp_sorted = sorted(
                exp_args_list,
                key=lambda a: json.dumps(a, sort_keys=True, ensure_ascii=False),
            )
            for oa, ea in zip(obs_sorted, exp_sorted, strict=True):
                if not json_args_equal(oa, ea):
                    return False

    return True


def score_decision(
    observation: DecisionObservation,
    expectation: EvalExpectation,
) -> bool:
    """Score a single decision observation against its expectation.

    Returns ``True`` if the observation passes all applicable conditions:

    - No error occurred (``error_type`` is ``None``).
    - Expected terminal kind matches (for RESPOND_NO_TOOL, CLARIFY_NO_TOOL).
    - Expected tool names and arguments match (for EXACT_TOOL_CALLS).
    - No extra tools emitted.
    - No tool calls for no-tool scenarios.

    Args:
        observation: The observed decision.
        expectation: The expected outcome.

    Returns:
        ``True`` if the decision passes, ``False`` otherwise.
    """
    # An errored observation cannot pass
    if observation.error_type is not None:
        return False

    observed_tools = observation.tool_calls
    observed_names = tuple(t.tool_name for t in observed_tools)

    if expectation.kind == ScenarioExpectationKind.NO_TOOL_ANY_TERMINAL:
        return len(observed_tools) == 0

    if expectation.kind == ScenarioExpectationKind.RESPOND_NO_TOOL:
        if len(observed_tools) != 0:
            return False
        return observation.terminal_kind == "respond"

    if expectation.kind == ScenarioExpectationKind.CLARIFY_NO_TOOL:
        if len(observed_tools) != 0:
            return False
        return observation.terminal_kind == "clarify"

    if expectation.kind == ScenarioExpectationKind.EXACT_TOOL_CALLS:
        expected = expectation.tool_calls
        expected_names = tuple(e.tool_name for e in expected)

        if len(observed_names) != len(expected_names):
            return False

        if expectation.order_sensitive:
            if observed_names != expected_names:
                return False
            for obs, exp in zip(observed_tools, expected, strict=True):
                if obs.tool_name != exp.tool_name:
                    return False
                if not json_args_equal(obs.arguments, exp.arguments):
                    return False
        else:
            observed_by_name: dict[str, list[dict[str, Any]]] = {}
            for obs in observed_tools:
                observed_by_name.setdefault(obs.tool_name, []).append(obs.arguments)

            expected_by_name: dict[str, list[dict[str, Any]]] = {}
            for exp in expected:
                expected_by_name.setdefault(exp.tool_name, []).append(exp.arguments)

            if set(observed_by_name) != set(expected_by_name):
                return False

            for name in observed_by_name:
                obs_args_list = observed_by_name[name]
                exp_args_list = expected_by_name[name]
                if len(obs_args_list) != len(exp_args_list):
                    return False
                obs_sorted = sorted(
                    obs_args_list,
                    key=lambda a: json.dumps(a, sort_keys=True, ensure_ascii=False),
                )
                exp_sorted = sorted(
                    exp_args_list,
                    key=lambda a: json.dumps(a, sort_keys=True, ensure_ascii=False),
                )
                for oa, ea in zip(obs_sorted, exp_sorted, strict=True):
                    if not json_args_equal(oa, ea):
                        return False

        return True


# ── Full-turn scoring ──────────────────────────────────────────────────────────


def score_full_turn(
    observation: FullTurnObservation,
    expectation: EvalExpectation,
) -> bool:
    """Score a full-turn observation against its expectation.

    Evaluates:
    - Terminal kind matches (for RESPOND_NO_TOOL, CLARIFY_NO_TOOL).
    - Tool names and arguments match (for EXACT_TOOL_CALLS).
    - No extra tools emitted beyond expected.
    - No tool calls for no-tool scenarios.

    Args:
        observation: The observed full turn.
        expectation: The expected outcome.

    Returns:
        ``True`` if the full turn passes, ``False`` otherwise.
    """
    if not observation.success:
        return False

    observed_tools = observation.executed_tool_calls
    observed_names = tuple(t.tool_name for t in observed_tools)

    if expectation.kind == ScenarioExpectationKind.NO_TOOL_ANY_TERMINAL:
        return len(observed_tools) == 0 and observation.terminal_kind is not None

    if expectation.kind == ScenarioExpectationKind.RESPOND_NO_TOOL:
        if len(observed_tools) != 0:
            return False
        return observation.terminal_kind == "respond"

    if expectation.kind == ScenarioExpectationKind.CLARIFY_NO_TOOL:
        if len(observed_tools) != 0:
            return False
        return observation.terminal_kind == "clarify"

    if expectation.kind == ScenarioExpectationKind.EXACT_TOOL_CALLS:
        expected = expectation.tool_calls
        expected_names = tuple(e.tool_name for e in expected)

        if len(observed_names) != len(expected_names):
            return False

        if expectation.order_sensitive:
            if observed_names != expected_names:
                return False
            for obs, exp in zip(observed_tools, expected, strict=True):
                if obs.tool_name != exp.tool_name:
                    return False
                if not json_args_equal(obs.arguments, exp.arguments):
                    return False
        else:
            observed_by_name: dict[str, list[dict[str, Any]]] = {}
            for obs in observed_tools:
                observed_by_name.setdefault(obs.tool_name, []).append(obs.arguments)

            expected_by_name: dict[str, list[dict[str, Any]]] = {}
            for exp in expected:
                expected_by_name.setdefault(exp.tool_name, []).append(exp.arguments)

            if set(observed_by_name) != set(expected_by_name):
                return False

            for name in observed_by_name:
                obs_args_list = observed_by_name[name]
                exp_args_list = expected_by_name[name]
                if len(obs_args_list) != len(exp_args_list):
                    return False
                obs_sorted = sorted(
                    obs_args_list,
                    key=lambda a: json.dumps(a, sort_keys=True, ensure_ascii=False),
                )
                exp_sorted = sorted(
                    exp_args_list,
                    key=lambda a: json.dumps(a, sort_keys=True, ensure_ascii=False),
                )
                for oa, ea in zip(obs_sorted, exp_sorted, strict=True):
                    if not json_args_equal(oa, ea):
                        return False

        return True

    return False


# ── Metric aggregation ─────────────────────────────────────────────────────────


def summarize_metrics(
    scenarios: list[EvalScenario],
    observations: list[DecisionObservation],
    runtime_label: str,
) -> list[MetricSummary]:
    """Compute aggregate metrics for one runtime's decision observations.

    Args:
        scenarios: The full list of eval scenarios.
        observations: The observations for this runtime (one per scenario
            per repetition).
        runtime_label: "reference" or "candidate".

    Returns:
        A list of ``MetricSummary`` instances.
    """
    obs_by_key: dict[tuple[str, int], DecisionObservation] = {}
    for obs in observations:
        obs_by_key[(obs.scenario_id, obs.repetition)] = obs

    scenario_passes: dict[str, list[bool]] = {}
    for s in scenarios:
        scenario_passes[s.scenario_id] = []
        for rep in range(3):
            key = (s.scenario_id, rep)
            obs = obs_by_key.get(key)
            if obs is not None:
                passed = score_decision(obs, s.expectation)
                scenario_passes[s.scenario_id].append(passed)

    scenario_success_count = 0
    scenario_total = len(scenarios)
    for _sid, passes in scenario_passes.items():
        if sum(passes) >= 2:
            scenario_success_count += 1

    exact_calls_scenarios = [
        s for s in scenarios if s.expectation.kind == ScenarioExpectationKind.EXACT_TOOL_CALLS
    ]
    exact_calls_total = len(exact_calls_scenarios) * 3

    # Tool-name accuracy: names/count/order only
    tool_name_passed = 0
    for s in exact_calls_scenarios:
        for rep in range(3):
            key = (s.scenario_id, rep)
            obs = obs_by_key.get(key)
            if obs is not None and score_tool_name(obs, s.expectation):
                tool_name_passed += 1

    # Argument exact match: names correct AND exact arguments
    arg_passed = 0
    for s in exact_calls_scenarios:
        for rep in range(3):
            key = (s.scenario_id, rep)
            obs = obs_by_key.get(key)
            if obs is not None and score_arguments(obs, s.expectation):
                arg_passed += 1

    total_emitted_calls = 0
    valid_calls = 0
    for obs in observations:
        # Skip errored observations for schema-valid denominator
        if obs.error_type is not None:
            continue
        for tc in obs.tool_calls:
            total_emitted_calls += 1
            if tc.schema_valid:
                valid_calls += 1

    no_tool_scenarios = [
        s
        for s in scenarios
        if s.expectation.kind
        in (
            ScenarioExpectationKind.RESPOND_NO_TOOL,
            ScenarioExpectationKind.CLARIFY_NO_TOOL,
            ScenarioExpectationKind.NO_TOOL_ANY_TERMINAL,
        )
    ]
    no_tool_total = len(no_tool_scenarios) * 3
    no_tool_false = 0
    for s in no_tool_scenarios:
        for rep in range(3):
            key = (s.scenario_id, rep)
            obs = obs_by_key.get(key)
            if obs is not None and len(obs.tool_calls) > 0:
                no_tool_false += 1

    missed = 0
    for s in exact_calls_scenarios:
        for rep in range(3):
            key = (s.scenario_id, rep)
            obs = obs_by_key.get(key)
            if obs is not None:
                expected_names = set(e.tool_name for e in s.expectation.tool_calls)
                observed_names = set(tc.tool_name for tc in obs.tool_calls)
                # Missed if any expected tool name is absent
                if not expected_names.issubset(observed_names):
                    missed += 1

    correct_abstention_count = no_tool_total - no_tool_false

    clarify_scenarios = [
        s for s in scenarios if s.expectation.kind == ScenarioExpectationKind.CLARIFY_NO_TOOL
    ]
    clarify_total = len(clarify_scenarios) * 3
    clarify_passed = 0
    for s in clarify_scenarios:
        for rep in range(3):
            key = (s.scenario_id, rep)
            obs = obs_by_key.get(key)
            if obs is not None and score_decision(obs, s.expectation):
                clarify_passed += 1

    false_write_count = 0  # run-level: runs with at least one false WRITE call
    false_write_denom = 0
    for s in scenarios:
        for rep in range(3):
            key = (s.scenario_id, rep)
            obs = obs_by_key.get(key)
            if obs is not None:
                is_write_expected = (
                    s.expectation.kind == ScenarioExpectationKind.EXACT_TOOL_CALLS
                    and any(e.tool_name.startswith("write_") for e in s.expectation.tool_calls)
                )
                # Only count in denominator if WRITE was actually visible
                write_visible = obs.exposed_tools is not None and obs.exposed_tools.has_write
                if not is_write_expected and write_visible:
                    false_write_denom += 1
                    # Run-level: +1 if at least one WRITE call in this run
                    if any(tc.tool_name.startswith("write_") for tc in obs.tool_calls):
                        false_write_count += 1

    hidden_write_denom = 0
    hidden_write_attempt_run_count = 0  # run-level: runs with at least one hidden WRITE attempt
    for s in scenarios:
        if s.hidden_write_expected:
            for rep in range(3):
                key = (s.scenario_id, rep)
                obs = obs_by_key.get(key)
                if obs is not None:
                    hidden_write_denom += 1
                    if any(tc.tool_name.startswith("write_") for tc in obs.tool_calls):
                        hidden_write_attempt_run_count += 1

    unnecessary_total = 0
    for s in scenarios:
        expected_count = len(s.expectation.tool_calls)
        for rep in range(3):
            key = (s.scenario_id, rep)
            obs = obs_by_key.get(key)
            if obs is not None:
                unnecessary = max(0, len(obs.tool_calls) - expected_count)
                unnecessary_total += unnecessary

    results: list[MetricSummary] = [
        MetricSummary(
            runtime_label=runtime_label,
            value=(scenario_success_count / scenario_total if scenario_total > 0 else 0.0),
            numerator=scenario_success_count,
            denominator=scenario_total,
        ),
        MetricSummary(
            runtime_label=runtime_label,
            value=(tool_name_passed / exact_calls_total if exact_calls_total > 0 else 0.0),
            numerator=tool_name_passed,
            denominator=exact_calls_total,
        ),
        MetricSummary(
            runtime_label=runtime_label,
            value=(arg_passed / exact_calls_total if exact_calls_total > 0 else 0.0),
            numerator=arg_passed,
            denominator=exact_calls_total,
        ),
        MetricSummary(
            runtime_label=runtime_label,
            value=(valid_calls / total_emitted_calls if total_emitted_calls > 0 else 1.0),
            numerator=valid_calls,
            denominator=total_emitted_calls,
        ),
        MetricSummary(
            runtime_label=runtime_label,
            value=(no_tool_false / no_tool_total if no_tool_total > 0 else 0.0),
            numerator=no_tool_false,
            denominator=no_tool_total,
        ),
        MetricSummary(
            runtime_label=runtime_label,
            value=(missed / exact_calls_total if exact_calls_total > 0 else 0.0),
            numerator=missed,
            denominator=exact_calls_total,
        ),
        MetricSummary(
            runtime_label=runtime_label,
            value=(correct_abstention_count / no_tool_total if no_tool_total > 0 else 1.0),
            numerator=correct_abstention_count,
            denominator=no_tool_total,
        ),
        MetricSummary(
            runtime_label=runtime_label,
            value=(clarify_passed / clarify_total if clarify_total > 0 else 1.0),
            numerator=clarify_passed,
            denominator=clarify_total,
        ),
        MetricSummary(
            runtime_label=runtime_label,
            value=(false_write_count / false_write_denom if false_write_denom > 0 else 0.0),
            numerator=false_write_count,
            denominator=false_write_denom,
        ),
        MetricSummary(
            runtime_label=runtime_label,
            value=(
                hidden_write_attempt_run_count / hidden_write_denom
                if hidden_write_denom > 0
                else 0.0
            ),
            numerator=hidden_write_attempt_run_count,
            denominator=hidden_write_denom,
        ),
        MetricSummary(
            runtime_label=runtime_label,
            value=float(unnecessary_total),
            numerator=unnecessary_total,
            denominator=1,
        ),
    ]

    return results


# ── Majority classification ────────────────────────────────────────────────────


def classify_majority(
    scenario_id: str,
    reference_observations: list[DecisionObservation],
    candidate_observations: list[DecisionObservation],
    expectation: EvalExpectation,
) -> ScenarioComparison:
    """Classify one scenario's majority result across both runtimes.

    Args:
        scenario_id: The scenario ID.
        reference_observations: Reference observations for this scenario
            (one per repetition).
        candidate_observations: Candidate observations for this scenario
            (one per repetition).
        expectation: The expected outcome.

    Returns:
        A ``ScenarioComparison`` with the majority classification.
    """
    ref_passes = sum(
        1
        for obs in reference_observations
        if obs.scenario_id == scenario_id and score_decision(obs, expectation)
    )
    cand_passes = sum(
        1
        for obs in candidate_observations
        if obs.scenario_id == scenario_id and score_decision(obs, expectation)
    )

    ref_majority = ref_passes >= 2
    cand_majority = cand_passes >= 2

    if ref_majority and cand_majority:
        classification: Literal[
            "BOTH_PASS",
            "REFERENCE_ONLY_PASS",
            "CANDIDATE_ONLY_PASS",
            "BOTH_FAIL",
        ] = "BOTH_PASS"
    elif ref_majority and not cand_majority:
        classification = "REFERENCE_ONLY_PASS"
    elif not ref_majority and cand_majority:
        classification = "CANDIDATE_ONLY_PASS"
    else:
        classification = "BOTH_FAIL"

    return ScenarioComparison(
        scenario_id=scenario_id,
        reference_passes=ref_passes,
        candidate_passes=cand_passes,
        classification=classification,
    )
