"""PAIM-13 frozen observation datasets and aggregate summaries.

This module defines frozen dataset DTOs for Layer A (decision) and
Layer B (full-turn) observations, plus aggregate summary functions
that consume frozen data without additional model calls.
"""

from __future__ import annotations

from dataclasses import dataclass

from tests.support.pydantic_ai_eval import (
    DecisionObservation,
    EvalScenario,
    FullTurnObservation,
    count_unauthorized_write_handler_executions,
    nearest_rank_percentile,
    score_full_turn,
)

# ── Frozen observation datasets ────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class FrozenDecisionDataset:
    """Frozen Layer A (decision) dataset collected exactly once.

    All observations are collected during a single fixture/setup phase.
    Consumers (scenario tests, aggregate metrics, latency) reuse the same
    frozen observations without calling the real model again.
    """

    scenarios: tuple[EvalScenario, ...]
    reference_observations: tuple[DecisionObservation, ...]
    candidate_observations: tuple[DecisionObservation, ...]

    def __post_init__(self) -> None:
        """Validate sample count and key uniqueness."""
        expected = len(self.scenarios) * 3
        assert len(self.reference_observations) == expected, (
            f"Expected {expected} reference observations, got {len(self.reference_observations)}"
        )
        assert len(self.candidate_observations) == expected, (
            f"Expected {expected} candidate observations, got {len(self.candidate_observations)}"
        )
        ref_keys = {(o.scenario_id, o.repetition) for o in self.reference_observations}
        cand_keys = {(o.scenario_id, o.repetition) for o in self.candidate_observations}
        assert len(ref_keys) == expected, (
            f"Reference observations have {len(ref_keys)} unique keys, expected {expected}"
        )
        assert len(cand_keys) == expected, (
            f"Candidate observations have {len(cand_keys)} unique keys, expected {expected}"
        )


@dataclass(frozen=True, slots=True)
class FrozenFullTurnDataset:
    """Frozen Layer B (full-turn) dataset collected exactly once.

    All observations are collected during a single fixture/setup phase.
    Consumers (scenario tests, aggregate metrics, latency) reuse the same
    frozen observations without calling the real model again.
    """

    scenarios: tuple[EvalScenario, ...]
    reference_observations: tuple[FullTurnObservation, ...]
    candidate_observations: tuple[FullTurnObservation, ...]

    def __post_init__(self) -> None:
        """Validate sample count and key uniqueness."""
        expected = len(self.scenarios) * 3
        assert len(self.reference_observations) == expected, (
            f"Expected {expected} reference observations, got {len(self.reference_observations)}"
        )
        assert len(self.candidate_observations) == expected, (
            f"Expected {expected} candidate observations, got {len(self.candidate_observations)}"
        )
        ref_keys = {(o.scenario_id, o.repetition) for o in self.reference_observations}
        cand_keys = {(o.scenario_id, o.repetition) for o in self.candidate_observations}
        assert len(ref_keys) == expected, (
            f"Reference observations have {len(ref_keys)} unique keys, expected {expected}"
        )
        assert len(cand_keys) == expected, (
            f"Candidate observations have {len(cand_keys)} unique keys, expected {expected}"
        )


# ── Full-turn aggregate summary ────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class FullTurnAggregateSummary:
    """Aggregate summary over a frozen Layer B dataset.

    All values derived from the frozen observations — no additional
    model calls.
    """

    runtime_label: str
    scenario_majority_success: float
    total_model_requests: int
    mean_model_requests: float
    total_initial_tool_calls: int
    mean_initial_tool_calls: float
    total_executed_tool_calls: int
    mean_executed_tool_calls: float
    total_handler_invocations: int
    mean_handler_invocations: float
    unauthorized_write_handler_count: int
    turns_with_excess_requests: int
    p50_seconds: float
    p95_seconds: float


def summarize_full_turn_aggregate(
    scenarios: list[EvalScenario],
    observations: list[FullTurnObservation],
    runtime_label: str,
) -> FullTurnAggregateSummary:
    """Compute aggregate summary over a frozen Layer B dataset.

    All values come from the observations, not expected scenario structure.
    No additional model calls.
    """
    n = len(observations)
    if n == 0:
        return FullTurnAggregateSummary(
            runtime_label=runtime_label,
            scenario_majority_success=0.0,
            total_model_requests=0,
            mean_model_requests=0.0,
            total_initial_tool_calls=0,
            mean_initial_tool_calls=0.0,
            total_executed_tool_calls=0,
            mean_executed_tool_calls=0.0,
            total_handler_invocations=0,
            mean_handler_invocations=0.0,
            unauthorized_write_handler_count=0,
            turns_with_excess_requests=0,
            p50_seconds=0.0,
            p95_seconds=0.0,
        )

    obs_by_scenario: dict[str, list[FullTurnObservation]] = {}
    for obs in observations:
        obs_by_scenario.setdefault(obs.scenario_id, []).append(obs)

    scenario_success_count = 0
    for sid, s_obs in obs_by_scenario.items():
        expectation = None
        for s in scenarios:
            if s.scenario_id == sid:
                expectation = s.expectation
                break
        if expectation is None:
            continue
        passes = sum(1 for o in s_obs if score_full_turn(o, expectation))
        if passes >= 2:
            scenario_success_count += 1

    # Build a deterministic scenario lookup
    scenario_map: dict[str, EvalScenario] = {s.scenario_id: s for s in scenarios}

    total_model_requests = sum(o.model_request_count for o in observations)
    total_initial_tool_calls = sum(o.tool_call_count for o in observations)
    total_executed_tool_calls = sum(o.tool_execution_count for o in observations)
    total_handler_invocations = sum(o.handler_call_count for o in observations)

    # Expectation-aware unauthorized WRITE accounting
    unauthorized_write_handler_count = 0
    for o in observations:
        scenario = scenario_map.get(o.scenario_id)
        if scenario is None:
            msg = f"Observation references unknown scenario_id={o.scenario_id!r}"
            raise ValueError(msg)
        unauthorized_write_handler_count += count_unauthorized_write_handler_executions(
            o, scenario.expectation
        )

    turns_with_excess_requests = sum(1 for o in observations if o.model_request_count > 2)

    durations = sorted(o.duration_seconds for o in observations)

    return FullTurnAggregateSummary(
        runtime_label=runtime_label,
        scenario_majority_success=(
            scenario_success_count / len(obs_by_scenario) if obs_by_scenario else 0.0
        ),
        total_model_requests=total_model_requests,
        mean_model_requests=total_model_requests / n,
        total_initial_tool_calls=total_initial_tool_calls,
        mean_initial_tool_calls=total_initial_tool_calls / n,
        total_executed_tool_calls=total_executed_tool_calls,
        mean_executed_tool_calls=total_executed_tool_calls / n,
        total_handler_invocations=total_handler_invocations,
        mean_handler_invocations=total_handler_invocations / n,
        unauthorized_write_handler_count=unauthorized_write_handler_count,
        turns_with_excess_requests=turns_with_excess_requests,
        p50_seconds=nearest_rank_percentile(durations, 50),
        p95_seconds=nearest_rank_percentile(durations, 95),
    )
