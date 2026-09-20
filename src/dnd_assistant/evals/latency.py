"""Provider-neutral latency aggregation over frozen eval observations.

Latency is descriptive measured evidence only: this module defines no
hardware-independent SLA, no maximum allowed duration and no pass/fail rule.
The aggregate is computed with the single accepted nearest-rank percentile
helper in :mod:`dnd_assistant.evals.metrics`.

Standard library + this package only.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from dnd_assistant.evals.metrics import nearest_rank_percentile


@dataclass(frozen=True, slots=True)
class LatencySummary:
    """Nearest-rank latency summary for one observation layer.

    Args:
        sample_count: Number of measured durations in this layer.
        p50_seconds: Nearest-rank p50, or ``None`` when there are no samples.
        p95_seconds: Nearest-rank p95, or ``None`` when there are no samples.
    """

    sample_count: int
    p50_seconds: float | None
    p95_seconds: float | None


@dataclass(frozen=True, slots=True)
class LatencyReport:
    """Latency summaries for both measurement layers of one run.

    Args:
        decision: Latency of the first semantic model request per sample.
        full_turn: Latency of the full runtime turn per sample.
    """

    decision: LatencySummary
    full_turn: LatencySummary


def summarize_latency(values: Sequence[float]) -> LatencySummary:
    """Aggregate durations with the existing nearest-rank percentile helper.

    The caller's sequence is never mutated.  An empty set is explicit:
    ``sample_count == 0`` and both percentiles are ``None``.

    Args:
        values: Non-negative finite durations in seconds, in any order.

    Returns:
        A ``LatencySummary`` derived from those exact values.

    Raises:
        ValueError: If any value is not a finite non-negative number.
    """
    durations: list[float] = []
    for value in values:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            raise ValueError(f"latency value must be a number, got {type(value).__name__}")
        seconds = float(value)
        if not math.isfinite(seconds):
            raise ValueError(f"latency value must be finite, got {value!r}")
        if seconds < 0:
            raise ValueError(f"latency value must be non-negative, got {value!r}")
        durations.append(seconds)

    if not durations:
        return LatencySummary(sample_count=0, p50_seconds=None, p95_seconds=None)

    return LatencySummary(
        sample_count=len(durations),
        p50_seconds=nearest_rank_percentile(durations, 50),
        p95_seconds=nearest_rank_percentile(durations, 95),
    )
