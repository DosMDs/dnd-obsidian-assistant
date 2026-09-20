"""Unit tests: provider-neutral latency aggregation (S14-07).

Deterministic injected durations only: no sleeping, no timing assertions.
"""

from __future__ import annotations

import math

import pytest

from dnd_assistant.evals.latency import (
    LatencyReport,
    LatencySummary,
    summarize_latency,
)
from dnd_assistant.evals.metrics import nearest_rank_percentile


def test_empty_sequence_is_explicit() -> None:
    summary = summarize_latency([])
    assert summary.sample_count == 0
    assert summary.p50_seconds is None
    assert summary.p95_seconds is None


def test_single_sample() -> None:
    summary = summarize_latency([0.5])
    assert summary.sample_count == 1
    assert summary.p50_seconds == 0.5
    assert summary.p95_seconds == 0.5


def test_uses_existing_nearest_rank_helper() -> None:
    values = [3.0, 1.0, 2.0, 5.0, 4.0]
    summary = summarize_latency(values)
    assert summary.sample_count == 5
    assert summary.p50_seconds == nearest_rank_percentile(values, 50)
    assert summary.p95_seconds == nearest_rank_percentile(values, 95)


def test_does_not_mutate_caller_input() -> None:
    values = [3.0, 1.0, 2.0, 5.0, 4.0]
    original = list(values)
    summarize_latency(values)
    assert values == original


def test_thirteen_sample_p95_may_equal_slowest() -> None:
    values = [float(i) for i in range(1, 14)]
    summary = summarize_latency(values)
    assert summary.sample_count == 13
    assert summary.p95_seconds == max(values)
    assert summary.p50_seconds == 7.0
    assert summary.p95_seconds == 13.0


def test_non_finite_rejected() -> None:
    with pytest.raises(ValueError, match="finite"):
        summarize_latency([1.0, math.inf])
    with pytest.raises(ValueError, match="finite"):
        summarize_latency([math.nan])


def test_negative_rejected() -> None:
    with pytest.raises(ValueError, match="non-negative"):
        summarize_latency([-0.1])


def test_bool_rejected() -> None:
    with pytest.raises(ValueError, match="number"):
        summarize_latency([True])  # type: ignore[list-item]


def test_latency_report_holds_both_layers() -> None:
    report = LatencyReport(
        decision=LatencySummary(2, 0.1, 0.2),
        full_turn=LatencySummary(2, 0.3, 0.4),
    )
    assert report.decision.sample_count == 2
    assert report.full_turn.p95_seconds == 0.4
