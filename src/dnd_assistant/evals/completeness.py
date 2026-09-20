"""Provider-neutral expected-sample completeness contract.

S14-02 intentionally summarizes only observations that actually exist.  This
module adds the separate run/report boundary that proves the exact expected
sample key set was observed for both observation layers.

It never modifies ``summarize_metrics`` and never turns a missing observation
into a metric denominator entry.  Standard library + this package only.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from dnd_assistant.evals.contracts import DecisionObservation, FullTurnObservation
from dnd_assistant.evals.dataset import EvalDataset

SampleKey = tuple[str, int]


@dataclass(frozen=True, slots=True)
class CompletenessReport:
    """Result of validating observed samples against the dataset plan.

    Args:
        expected_sample_count: Expected samples (cases x repetitions).
        observed_decision_count: Decision observations present.
        observed_full_turn_count: Full-turn observations present.
        missing: Expected keys with no observation.
        duplicates: Keys observed more than once.
        unknown_scenarios: Observed scenario IDs absent from the dataset.
        out_of_range_repetitions: Observed repetitions outside the plan.
        ordering_ok: Whether both layers observe expected keys in expected order.
        complete: Whether the run satisfies the full expected sample contract.
        errors: Human-readable validation messages (stable, sorted).
    """

    expected_sample_count: int
    observed_decision_count: int
    observed_full_turn_count: int
    missing: tuple[SampleKey, ...]
    duplicates: tuple[SampleKey, ...]
    unknown_scenarios: tuple[str, ...]
    out_of_range_repetitions: tuple[SampleKey, ...]
    ordering_ok: bool
    complete: bool
    errors: tuple[str, ...]


def expected_sample_keys(dataset: EvalDataset) -> tuple[SampleKey, ...]:
    """Return the expected ``(scenario_id, repetition)`` keys in plan order.

    Order is dataset case order, then repetition ascending.
    """
    keys: list[SampleKey] = []
    for case in dataset.cases:
        scenario_id = case.scenario.scenario_id
        for repetition in range(dataset.sample_plan.repetitions):
            keys.append((scenario_id, repetition))
    return tuple(keys)


def validate_completeness(
    dataset: EvalDataset,
    decision_observations: Sequence[DecisionObservation],
    full_turn_observations: Sequence[FullTurnObservation],
) -> CompletenessReport:
    """Validate both observation layers against the dataset sample plan."""
    expected = expected_sample_keys(dataset)
    known_scenarios = set(dataset.scenario_ids)
    repetitions = dataset.sample_plan.repetitions

    errors: list[str] = []
    unknown: set[str] = set()
    out_of_range: set[SampleKey] = set()
    duplicates: set[SampleKey] = set()

    decision_keys = _validate_layer(
        "decision",
        decision_observations,
        known_scenarios,
        repetitions,
        unknown,
        out_of_range,
        duplicates,
    )
    full_turn_keys = _validate_layer(
        "full_turn",
        full_turn_observations,
        known_scenarios,
        repetitions,
        unknown,
        out_of_range,
        duplicates,
    )

    missing: list[SampleKey] = []
    for layer_name, layer_keys in (("decision", decision_keys), ("full_turn", full_turn_keys)):
        present = set(layer_keys)
        for key in expected:
            if key not in present:
                missing.append(key)
                errors.append(f"missing {layer_name} sample {key}")

    for key in sorted(duplicates):
        errors.append(f"duplicate sample {key}")
    for scenario_id in sorted(unknown):
        errors.append(f"unknown scenario {scenario_id!r}")
    for key in sorted(out_of_range):
        errors.append(f"out-of-range repetition {key}")

    ordering_ok = decision_keys == list(expected) and full_turn_keys == list(expected)
    if not ordering_ok:
        errors.append("observation order does not match expected sample order")

    complete = not missing and not duplicates and not unknown and not out_of_range and ordering_ok

    return CompletenessReport(
        expected_sample_count=len(expected),
        observed_decision_count=len(decision_observations),
        observed_full_turn_count=len(full_turn_observations),
        missing=tuple(missing),
        duplicates=tuple(sorted(duplicates)),
        unknown_scenarios=tuple(sorted(unknown)),
        out_of_range_repetitions=tuple(sorted(out_of_range)),
        ordering_ok=ordering_ok,
        complete=complete,
        errors=tuple(errors),
    )


def _validate_layer(
    _layer: str,
    observations: Sequence[DecisionObservation] | Sequence[FullTurnObservation],
    known_scenarios: set[str],
    repetitions: int,
    unknown: set[str],
    out_of_range: set[SampleKey],
    duplicates: set[SampleKey],
) -> list[SampleKey]:
    keys: list[SampleKey] = []
    seen: set[SampleKey] = set()
    for observation in observations:
        key: SampleKey = (observation.scenario_id, observation.repetition)
        keys.append(key)
        if observation.scenario_id not in known_scenarios:
            unknown.add(observation.scenario_id)
        elif observation.repetition < 0 or observation.repetition >= repetitions:
            out_of_range.add(key)
        if key in seen:
            duplicates.add(key)
        seen.add(key)
    return keys
