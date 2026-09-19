"""Deterministic decision and full-turn scoring.

Pure functions over frozen observation DTOs.  Standard library only; this
module must never import another ``dnd_assistant`` layer or any provider
framework.

Semantics fixed here:

- strict JSON structural-type equality (``0 != False``, ``1 != True``,
  ``1 != 1.0``);
- unordered tool-call comparison uses true multiset semantics, so duplicate
  tool names/arguments are handled exactly;
- a runtime/model error can never be a successful decision, abstention or
  clarification;
- ``NO_TOOL_ANY_TERMINAL`` requires a real terminal outcome (never ``None``).
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Sequence
from typing import Any

from dnd_assistant.evals.contracts import (
    DecisionObservation,
    EvalExpectation,
    ExpectedToolCall,
    FullTurnObservation,
    ScenarioExpectationKind,
    ToolCallObservation,
)

# A real terminal outcome must be one of the accepted terminal kinds.
_REAL_TERMINAL_KINDS = frozenset({"respond", "clarify"})

_NO_TOOL_KINDS = frozenset(
    {
        ScenarioExpectationKind.RESPOND_NO_TOOL,
        ScenarioExpectationKind.CLARIFY_NO_TOOL,
        ScenarioExpectationKind.NO_TOOL_ANY_TERMINAL,
    }
)


# ── Strict JSON argument comparison ────────────────────────────────────────


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
    """
    return _strict_json_value_equal(left, right)


def _strict_json_value_equal(left: object, right: object) -> bool:
    """Recursive strict JSON value comparison preserving exact types."""
    if type(left) is not type(right):
        return False
    if isinstance(left, dict) and isinstance(right, dict):
        if len(left) != len(right):
            return False
        for key in left:
            if key not in right:
                return False
            if not _strict_json_value_equal(left[key], right[key]):
                return False
        return True
    if isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            return False
        return all(_strict_json_value_equal(a, b) for a, b in zip(left, right, strict=True))
    return left == right


# ── Internal call-matching helpers ─────────────────────────────────────────


def _ordered_calls_match(
    observed: Sequence[ToolCallObservation],
    expected: Sequence[ExpectedToolCall],
    *,
    match_arguments: bool,
) -> bool:
    if len(observed) != len(expected):
        return False
    for obs, exp in zip(observed, expected, strict=True):
        if obs.tool_name != exp.tool_name:
            return False
        if match_arguments and not json_args_equal(obs.arguments, exp.arguments):
            return False
    return True


def _unordered_names_match(
    observed: Sequence[ToolCallObservation], expected: Sequence[ExpectedToolCall]
) -> bool:
    return Counter(o.tool_name for o in observed) == Counter(e.tool_name for e in expected)


def _unordered_arguments_match(
    observed: Sequence[ToolCallObservation], expected: Sequence[ExpectedToolCall]
) -> bool:
    if len(observed) != len(expected):
        return False

    observed_by_name: dict[str, list[dict[str, Any]]] = {}
    for obs in observed:
        observed_by_name.setdefault(obs.tool_name, []).append(obs.arguments)

    expected_by_name: dict[str, list[dict[str, Any]]] = {}
    for exp in expected:
        expected_by_name.setdefault(exp.tool_name, []).append(exp.arguments)

    if set(observed_by_name) != set(expected_by_name):
        return False

    for name, observed_args in observed_by_name.items():
        expected_args = expected_by_name[name]
        if len(observed_args) != len(expected_args):
            return False
        observed_sorted = sorted(
            observed_args, key=lambda a: json.dumps(a, sort_keys=True, ensure_ascii=False)
        )
        expected_sorted = sorted(
            expected_args, key=lambda a: json.dumps(a, sort_keys=True, ensure_ascii=False)
        )
        for obs_args, exp_args in zip(observed_sorted, expected_sorted, strict=True):
            if not json_args_equal(obs_args, exp_args):
                return False
    return True


# ── Decision scoring ───────────────────────────────────────────────────────


def score_tool_name(
    observation: DecisionObservation,
    expectation: EvalExpectation,
) -> bool:
    """Score tool-name accuracy only (names/count/order), ignoring arguments.

    An errored observation always returns ``False``.  For unordered
    expectations a true multiset comparison is used, so duplicate tool names
    must match exactly (e.g. expected ``A, A, B`` does not accept observed
    ``A, B, B``).
    """
    if observation.error_type is not None:
        return False

    observed = observation.tool_calls

    if expectation.kind in _NO_TOOL_KINDS:
        return len(observed) == 0

    if expectation.kind == ScenarioExpectationKind.EXACT_TOOL_CALLS:
        expected = expectation.tool_calls
        if len(observed) != len(expected):
            return False
        if expectation.order_sensitive:
            return _ordered_calls_match(observed, expected, match_arguments=False)
        return _unordered_names_match(observed, expected)

    return False


def score_arguments(
    observation: DecisionObservation,
    expectation: EvalExpectation,
) -> bool:
    """Score argument exact match (tool names must also be correct).

    Returns ``True`` only if tool names/count/order match and every observed
    call's arguments match exactly.  Non-tool expectations pass when their
    no-tool condition holds.
    """
    if not score_tool_name(observation, expectation):
        return False

    if expectation.kind != ScenarioExpectationKind.EXACT_TOOL_CALLS:
        return True

    observed = observation.tool_calls
    expected = expectation.tool_calls
    if expectation.order_sensitive:
        return _ordered_calls_match(observed, expected, match_arguments=True)
    return _unordered_arguments_match(observed, expected)


def score_decision(
    observation: DecisionObservation,
    expectation: EvalExpectation,
) -> bool:
    """Score a single decision observation against its expectation.

    An errored observation can never pass.  For ``NO_TOOL_ANY_TERMINAL`` a
    real terminal outcome is required: zero tool calls with
    ``terminal_kind is None`` does not pass.
    """
    if observation.error_type is not None:
        return False

    observed = observation.tool_calls

    if expectation.kind == ScenarioExpectationKind.NO_TOOL_ANY_TERMINAL:
        return len(observed) == 0 and observation.terminal_kind in _REAL_TERMINAL_KINDS

    if expectation.kind == ScenarioExpectationKind.RESPOND_NO_TOOL:
        return len(observed) == 0 and observation.terminal_kind == "respond"

    if expectation.kind == ScenarioExpectationKind.CLARIFY_NO_TOOL:
        return len(observed) == 0 and observation.terminal_kind == "clarify"

    if expectation.kind == ScenarioExpectationKind.EXACT_TOOL_CALLS:
        return score_arguments(observation, expectation)

    return False


# ── Full-turn scoring ──────────────────────────────────────────────────────


def score_full_turn(
    observation: FullTurnObservation,
    expectation: EvalExpectation,
) -> bool:
    """Score a full-turn observation against its expectation.

    An errored or unsuccessful turn can never pass.  For
    ``NO_TOOL_ANY_TERMINAL`` a real terminal outcome is required.
    """
    if observation.error_type is not None:
        return False
    if not observation.success:
        return False

    observed = observation.executed_tool_calls

    if expectation.kind == ScenarioExpectationKind.NO_TOOL_ANY_TERMINAL:
        return len(observed) == 0 and observation.terminal_kind in _REAL_TERMINAL_KINDS

    if expectation.kind == ScenarioExpectationKind.RESPOND_NO_TOOL:
        return len(observed) == 0 and observation.terminal_kind == "respond"

    if expectation.kind == ScenarioExpectationKind.CLARIFY_NO_TOOL:
        return len(observed) == 0 and observation.terminal_kind == "clarify"

    if expectation.kind == ScenarioExpectationKind.EXACT_TOOL_CALLS:
        expected = expectation.tool_calls
        if len(observed) != len(expected):
            return False
        if expectation.order_sensitive:
            return _ordered_calls_match(observed, expected, match_arguments=True)
        return _unordered_arguments_match(observed, expected)

    return False
