"""Provider-neutral deterministic evaluation package.

Public deterministic contract for model/runtime evaluation: scenario
expectations, observation DTOs, strict-JSON scoring, stable metric identities
and WRITE execution accounting.

This package depends on the Python standard library and its own modules only.
It must never import another ``dnd_assistant`` layer, Ollama, Pydantic AI,
Textual, Typer or any concrete model/provider, and must perform no network
activity or environment/config loading at import time.
"""

from __future__ import annotations

from dnd_assistant.evals.contracts import (
    DecisionObservation,
    EvalExpectation,
    EvalScenario,
    ExpectedToolCall,
    ExposedToolInfo,
    FullTurnObservation,
    ScenarioExpectationKind,
    ToolCallObservation,
)
from dnd_assistant.evals.metrics import (
    MetricId,
    MetricSummary,
    nearest_rank_percentile,
    summarize_metrics,
)
from dnd_assistant.evals.scoring import (
    json_args_equal,
    score_arguments,
    score_decision,
    score_full_turn,
    score_tool_name,
)
from dnd_assistant.evals.write_accounting import (
    count_unauthorized_write_handler_executions,
)

__all__ = [
    "DecisionObservation",
    "EvalExpectation",
    "EvalScenario",
    "ExpectedToolCall",
    "ExposedToolInfo",
    "FullTurnObservation",
    "MetricId",
    "MetricSummary",
    "ScenarioExpectationKind",
    "ToolCallObservation",
    "count_unauthorized_write_handler_executions",
    "json_args_equal",
    "nearest_rank_percentile",
    "score_arguments",
    "score_decision",
    "score_full_turn",
    "score_tool_name",
    "summarize_metrics",
]
