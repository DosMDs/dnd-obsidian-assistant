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

from dnd_assistant.evals.completeness import (
    CompletenessReport,
    expected_sample_keys,
    validate_completeness,
)
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
from dnd_assistant.evals.dataset import (
    EvalCase,
    EvalDataset,
    EvalExecutionSpec,
    EvalPermission,
    EvalQualityPolicy,
    EvalSamplePlan,
    EvalSessionState,
)
from dnd_assistant.evals.latency import (
    LatencyReport,
    LatencySummary,
    summarize_latency,
)
from dnd_assistant.evals.metrics import (
    MetricId,
    MetricSummary,
    nearest_rank_percentile,
    summarize_metrics,
)
from dnd_assistant.evals.report import (
    REPORT_SCHEMA_VERSION,
    BaselineComparison,
    BaselineStatus,
    EvalQualityResult,
    EvalReport,
    EvalReportIdentity,
    EvalRuntimeInfo,
    EvalRunValidity,
    EvalSafetyResult,
    EvalSampleScore,
    MetricDelta,
    build_eval_report,
    compare_eval_reports,
)
from dnd_assistant.evals.report_json import report_from_json, report_to_json
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
    "REPORT_SCHEMA_VERSION",
    "BaselineComparison",
    "BaselineStatus",
    "CompletenessReport",
    "DecisionObservation",
    "EvalCase",
    "EvalDataset",
    "EvalExecutionSpec",
    "EvalExpectation",
    "EvalPermission",
    "EvalQualityPolicy",
    "EvalQualityResult",
    "EvalReport",
    "EvalReportIdentity",
    "EvalRuntimeInfo",
    "EvalRunValidity",
    "EvalSafetyResult",
    "EvalSamplePlan",
    "EvalSampleScore",
    "EvalScenario",
    "EvalSessionState",
    "ExpectedToolCall",
    "ExposedToolInfo",
    "FullTurnObservation",
    "LatencyReport",
    "LatencySummary",
    "MetricDelta",
    "MetricId",
    "MetricSummary",
    "ScenarioExpectationKind",
    "ToolCallObservation",
    "build_eval_report",
    "compare_eval_reports",
    "count_unauthorized_write_handler_executions",
    "expected_sample_keys",
    "json_args_equal",
    "nearest_rank_percentile",
    "report_from_json",
    "report_to_json",
    "score_arguments",
    "score_decision",
    "score_full_turn",
    "score_tool_name",
    "summarize_latency",
    "summarize_metrics",
    "validate_completeness",
]
