"""Deterministic tests for the provider-neutral eval scoring contract.

All offline: stdlib and ``dnd_assistant.evals`` only, no network, no model.
"""

from __future__ import annotations

import pytest

from dnd_assistant.evals import (
    DecisionObservation,
    EvalExpectation,
    ExpectedToolCall,
    FullTurnObservation,
    ScenarioExpectationKind,
    ToolCallObservation,
    json_args_equal,
    nearest_rank_percentile,
    score_arguments,
    score_decision,
    score_full_turn,
    score_tool_name,
)


def _tc(
    tool_name: str,
    arguments: dict[str, object] | None = None,
    *,
    schema_valid: bool = True,
    is_write: bool = False,
    call_id: str = "1",
) -> ToolCallObservation:
    return ToolCallObservation(
        tool_name=tool_name,
        arguments=arguments if arguments is not None else {},
        call_id=call_id,
        schema_valid=schema_valid,
        is_write=is_write,
    )


def _decision(
    tool_calls: tuple[ToolCallObservation, ...] = (),
    *,
    terminal_kind: str | None = None,
    error_type: str | None = None,
) -> DecisionObservation:
    return DecisionObservation(
        scenario_id="test",
        repetition=0,
        duration_seconds=0.1,
        tool_calls=tool_calls,
        terminal_kind=terminal_kind,
        error_type=error_type,
    )


def _expect(names: tuple[str, ...], *, order_sensitive: bool = True) -> EvalExpectation:
    return EvalExpectation(
        kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
        tool_calls=tuple(ExpectedToolCall(tool_name=n, arguments={"n": n}) for n in names),
        order_sensitive=order_sensitive,
    )


# ── json_args_equal ────────────────────────────────────────────────────────


class TestJsonArgsEqual:
    def test_equal_dicts_key_order_independent(self) -> None:
        assert json_args_equal({"a": 1, "b": "x"}, {"b": "x", "a": 1})

    def test_list_order_matters(self) -> None:
        assert not json_args_equal({"a": [1, 2]}, {"a": [2, 1]})
        assert json_args_equal({"a": [1, 2]}, {"a": [1, 2]})

    @pytest.mark.parametrize(
        ("left", "right"),
        [
            ({"a": 0}, {"a": False}),
            ({"a": 1}, {"a": True}),
            ({"a": 1}, {"a": 1.0}),
            ({"a": "1"}, {"a": 1}),
        ],
    )
    def test_strict_type_mismatch(self, left: dict[str, object], right: dict[str, object]) -> None:
        assert not json_args_equal(left, right)

    def test_nested_strict_types(self) -> None:
        assert not json_args_equal({"x": {"y": 1}}, {"x": {"y": True}})
        assert not json_args_equal({"x": {"y": 1}}, {"x": {"y": 1.0}})
        assert json_args_equal({"x": {"y": 1}}, {"x": {"y": 1}})

    def test_different_keys(self) -> None:
        assert not json_args_equal({"a": 1}, {"b": 1})


# ── score_tool_name ────────────────────────────────────────────────────────


class TestScoreToolName:
    def test_respond_no_tool_pass(self) -> None:
        assert score_tool_name(
            _decision(terminal_kind="respond"),
            EvalExpectation(kind=ScenarioExpectationKind.RESPOND_NO_TOOL),
        )

    def test_no_tool_with_call_fails(self) -> None:
        assert not score_tool_name(
            _decision((_tc("read_npc"),)),
            EvalExpectation(kind=ScenarioExpectationKind.RESPOND_NO_TOOL),
        )

    def test_exact_names_ignore_arguments(self) -> None:
        assert score_tool_name(
            _decision((_tc("read_npc", {"name": "WRONG"}),)),
            _expect(("read_npc",)),
        )

    def test_wrong_name_fails(self) -> None:
        assert not score_tool_name(_decision((_tc("read_location"),)), _expect(("read_npc",)))

    def test_ordered_names(self) -> None:
        assert score_tool_name(
            _decision((_tc("a"), _tc("b"))), _expect(("a", "b"), order_sensitive=True)
        )
        assert not score_tool_name(
            _decision((_tc("b"), _tc("a"))), _expect(("a", "b"), order_sensitive=True)
        )

    def test_unordered_duplicate_multiset_mismatch_fails(self) -> None:
        # expected A,A,B ; observed A,B,B — a set comparison would wrongly pass.
        assert not score_tool_name(
            _decision((_tc("a"), _tc("b"), _tc("b"))),
            _expect(("a", "a", "b"), order_sensitive=False),
        )

    def test_unordered_duplicate_multiset_match_passes(self) -> None:
        assert score_tool_name(
            _decision((_tc("b"), _tc("a"), _tc("a"))),
            _expect(("a", "a", "b"), order_sensitive=False),
        )

    def test_errored_observation_fails(self) -> None:
        assert not score_tool_name(
            _decision((_tc("read_npc"),), error_type="ModelError"), _expect(("read_npc",))
        )


# ── score_arguments ────────────────────────────────────────────────────────


class TestScoreArguments:
    def test_exact_match(self) -> None:
        expectation = EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(ExpectedToolCall(tool_name="read_npc", arguments={"name": "Arlen"}),),
        )
        assert score_arguments(_decision((_tc("read_npc", {"name": "Arlen"}),)), expectation)

    def test_wrong_arguments_fail(self) -> None:
        expectation = EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(ExpectedToolCall(tool_name="read_npc", arguments={"name": "Arlen"}),),
        )
        assert not score_arguments(_decision((_tc("read_npc", {"name": "WRONG"}),)), expectation)

    def test_unordered_duplicate_arguments_multiset(self) -> None:
        expectation = EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(
                ExpectedToolCall(tool_name="a", arguments={"i": 1}),
                ExpectedToolCall(tool_name="a", arguments={"i": 2}),
            ),
            order_sensitive=False,
        )
        assert score_arguments(_decision((_tc("a", {"i": 2}), _tc("a", {"i": 1}))), expectation)
        assert not score_arguments(_decision((_tc("a", {"i": 1}), _tc("a", {"i": 1}))), expectation)

    def test_no_tool_expectation(self) -> None:
        assert score_arguments(
            _decision(terminal_kind="respond"),
            EvalExpectation(kind=ScenarioExpectationKind.RESPOND_NO_TOOL),
        )


# ── score_decision ─────────────────────────────────────────────────────────


class TestScoreDecision:
    def test_respond(self) -> None:
        assert score_decision(
            _decision(terminal_kind="respond"),
            EvalExpectation(kind=ScenarioExpectationKind.RESPOND_NO_TOOL),
        )

    def test_respond_wrong_terminal(self) -> None:
        assert not score_decision(
            _decision(terminal_kind="clarify"),
            EvalExpectation(kind=ScenarioExpectationKind.RESPOND_NO_TOOL),
        )

    def test_clarify(self) -> None:
        assert score_decision(
            _decision(terminal_kind="clarify"),
            EvalExpectation(kind=ScenarioExpectationKind.CLARIFY_NO_TOOL),
        )

    def test_no_tool_any_terminal_requires_real_terminal(self) -> None:
        expectation = EvalExpectation(kind=ScenarioExpectationKind.NO_TOOL_ANY_TERMINAL)
        assert score_decision(_decision(terminal_kind="respond"), expectation)
        assert not score_decision(_decision(terminal_kind=None), expectation)

    def test_exact_ordered(self) -> None:
        assert score_decision(_decision((_tc("a", {"n": "a"}),)), _expect(("a",)))
        assert not score_decision(_decision((_tc("b", {"n": "a"}),)), _expect(("a",)))

    def test_extra_call_fails(self) -> None:
        assert not score_decision(_decision((_tc("a"), _tc("b"))), _expect(("a",)))

    def test_errored_never_succeeds(self) -> None:
        assert not score_decision(
            _decision(terminal_kind="respond", error_type="ModelError"),
            EvalExpectation(kind=ScenarioExpectationKind.RESPOND_NO_TOOL),
        )


# ── score_full_turn ────────────────────────────────────────────────────────


def _full(
    *,
    success: bool = True,
    terminal_kind: str | None = "respond",
    executed: tuple[ToolCallObservation, ...] = (),
    error_type: str | None = None,
) -> FullTurnObservation:
    return FullTurnObservation(
        scenario_id="test",
        repetition=0,
        duration_seconds=0.1,
        success=success,
        terminal_kind=terminal_kind,
        executed_tool_calls=executed,
        error_type=error_type,
    )


class TestScoreFullTurn:
    def test_respond(self) -> None:
        assert score_full_turn(
            _full(terminal_kind="respond"),
            EvalExpectation(kind=ScenarioExpectationKind.RESPOND_NO_TOOL),
        )

    def test_failed_turn_never_succeeds(self) -> None:
        assert not score_full_turn(
            _full(success=False),
            EvalExpectation(kind=ScenarioExpectationKind.RESPOND_NO_TOOL),
        )

    def test_no_tool_any_terminal_requires_real_terminal(self) -> None:
        expectation = EvalExpectation(kind=ScenarioExpectationKind.NO_TOOL_ANY_TERMINAL)
        assert score_full_turn(_full(terminal_kind="clarify"), expectation)
        assert not score_full_turn(_full(terminal_kind=None), expectation)

    def test_exact_executed_calls(self) -> None:
        expectation = EvalExpectation(
            kind=ScenarioExpectationKind.EXACT_TOOL_CALLS,
            tool_calls=(ExpectedToolCall(tool_name="read_npc", arguments={"name": "Arlen"}),),
        )
        assert score_full_turn(_full(executed=(_tc("read_npc", {"name": "Arlen"}),)), expectation)
        assert not score_full_turn(_full(executed=()), expectation)


# ── nearest_rank_percentile ────────────────────────────────────────────────


class TestNearestRankPercentile:
    def test_unsorted_input(self) -> None:
        assert nearest_rank_percentile([4.0, 1.0, 3.0, 2.0], 50) == 2.0

    def test_does_not_mutate_input(self) -> None:
        values = [4.0, 1.0, 3.0, 2.0]
        nearest_rank_percentile(values, 95)
        assert values == [4.0, 1.0, 3.0, 2.0]

    def test_p95(self) -> None:
        values = [float(i) for i in range(1, 11)]
        assert nearest_rank_percentile(values, 95) == 10.0

    def test_p0_and_p100(self) -> None:
        assert nearest_rank_percentile([3.0, 1.0, 2.0], 0) == 1.0
        assert nearest_rank_percentile([3.0, 1.0, 2.0], 100) == 3.0

    def test_single_value(self) -> None:
        assert nearest_rank_percentile([42.0], 95) == 42.0

    def test_empty_raises(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            nearest_rank_percentile([], 50)

    @pytest.mark.parametrize("percentile", [-1, 101])
    def test_invalid_percentile_raises(self, percentile: int) -> None:
        with pytest.raises(ValueError, match="Percentile"):
            nearest_rank_percentile([1.0], percentile)
