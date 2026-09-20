"""Unit tests: expected-sample completeness contract (S14-06)."""

from __future__ import annotations

from dnd_assistant.evals.completeness import (
    expected_sample_keys,
    validate_completeness,
)
from dnd_assistant.evals.contracts import DecisionObservation, FullTurnObservation
from dnd_assistant.evals.datasets.product_v1 import build_product_v1_dataset


def _decision(scenario_id: str, repetition: int = 0) -> DecisionObservation:
    return DecisionObservation(scenario_id=scenario_id, repetition=repetition, duration_seconds=0.0)


def _full_turn(scenario_id: str, repetition: int = 0) -> FullTurnObservation:
    return FullTurnObservation(
        scenario_id=scenario_id, repetition=repetition, duration_seconds=0.0, success=True
    )


def _complete_dataset_observations() -> tuple[list[DecisionObservation], list[FullTurnObservation]]:
    dataset = build_product_v1_dataset()
    decisions = [_decision(case.scenario.scenario_id) for case in dataset.cases]
    full_turns = [_full_turn(case.scenario.scenario_id) for case in dataset.cases]
    return decisions, full_turns


def test_expected_keys_order_and_count() -> None:
    dataset = build_product_v1_dataset()
    keys = expected_sample_keys(dataset)
    assert keys == tuple((case.scenario.scenario_id, 0) for case in dataset.cases)
    assert len(keys) == 13


def test_complete_run_is_accepted() -> None:
    dataset = build_product_v1_dataset()
    decisions, full_turns = _complete_dataset_observations()
    report = validate_completeness(dataset, decisions, full_turns)
    assert report.complete
    assert report.expected_sample_count == 13
    assert report.ordering_ok
    assert report.errors == ()


def test_missing_sample_rejected() -> None:
    dataset = build_product_v1_dataset()
    decisions, full_turns = _complete_dataset_observations()
    report = validate_completeness(dataset, decisions[:-1], full_turns[:-1])
    assert not report.complete
    assert report.missing
    assert any("missing" in error for error in report.errors)


def test_duplicate_sample_rejected() -> None:
    dataset = build_product_v1_dataset()
    decisions, full_turns = _complete_dataset_observations()
    decisions = [*decisions, decisions[0]]
    full_turns = [*full_turns, full_turns[0]]
    report = validate_completeness(dataset, decisions, full_turns)
    assert not report.complete
    assert report.duplicates


def test_unknown_scenario_rejected() -> None:
    dataset = build_product_v1_dataset()
    decisions, full_turns = _complete_dataset_observations()
    decisions = [*decisions, _decision("EVAL-P1-999")]
    full_turns = [*full_turns, _full_turn("EVAL-P1-999")]
    report = validate_completeness(dataset, decisions, full_turns)
    assert not report.complete
    assert "EVAL-P1-999" in report.unknown_scenarios


def test_out_of_range_repetition_rejected() -> None:
    dataset = build_product_v1_dataset()
    decisions, full_turns = _complete_dataset_observations()
    decisions = [*decisions, _decision("EVAL-P1-001", repetition=5)]
    full_turns = [*full_turns, _full_turn("EVAL-P1-001", repetition=5)]
    report = validate_completeness(dataset, decisions, full_turns)
    assert not report.complete
    assert report.out_of_range_repetitions


def test_wrong_order_rejected() -> None:
    dataset = build_product_v1_dataset()
    decisions, full_turns = _complete_dataset_observations()
    reversed_decisions = list(reversed(decisions))
    reversed_full_turns = list(reversed(full_turns))
    report = validate_completeness(dataset, reversed_decisions, reversed_full_turns)
    assert not report.complete
    assert not report.ordering_ok
