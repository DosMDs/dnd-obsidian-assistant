"""Provider-neutral eval report contract, evaluation and comparison.

Builds a stable machine-readable report from frozen decision/full-turn
observations, the dataset ground truth, the sample-completeness contract and
the dataset quality policy.  Safety is a hard invariant; quality is a product
policy.

Standard library + this package only.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum

from dnd_assistant.evals.completeness import CompletenessReport, validate_completeness
from dnd_assistant.evals.contracts import (
    DecisionObservation,
    FullTurnObservation,
)
from dnd_assistant.evals.dataset import EvalDataset
from dnd_assistant.evals.metrics import MetricId, MetricSummary, summarize_metrics
from dnd_assistant.evals.scoring import score_decision, score_full_turn
from dnd_assistant.evals.write_accounting import count_unauthorized_write_handler_executions

REPORT_SCHEMA_VERSION = 1


# ── Report DTOs ────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class EvalReportIdentity:
    """Stable identity binding that prevents silent ground-truth drift."""

    report_schema_version: int
    dataset_id: str
    dataset_version: str
    dataset_fingerprint: str
    sample_plan_id: str
    sample_plan_fingerprint: str
    prompt_version: str


@dataclass(frozen=True, slots=True)
class EvalRuntimeInfo:
    """Runtime identity of the measured candidate."""

    mode: str
    label: str
    metadata: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class EvalSafetyResult:
    """Hard system-safety result (never a quality threshold)."""

    unauthorized_write_handler_execution_count: int
    passed: bool


@dataclass(frozen=True, slots=True)
class EvalQualityResult:
    """Product-quality gate result for ``false_write_tool_call_rate``."""

    max_false_write_tool_call_rate: float | None
    false_write_rate_value: float | None
    false_write_numerator: int
    false_write_denominator: int
    passed: bool


@dataclass(frozen=True, slots=True)
class EvalSampleScore:
    """Per-sample decision/full-turn pass flags."""

    scenario_id: str
    repetition: int
    decision_pass: bool
    full_turn_pass: bool


@dataclass(frozen=True, slots=True)
class EvalReport:
    """Complete eval report for one measured candidate."""

    identity: EvalReportIdentity
    runtime: EvalRuntimeInfo
    sample_contract: CompletenessReport
    decision_observations: tuple[DecisionObservation, ...]
    full_turn_observations: tuple[FullTurnObservation, ...]
    metrics: tuple[MetricSummary, ...]
    sample_scores: tuple[EvalSampleScore, ...]
    safety: EvalSafetyResult
    quality: EvalQualityResult
    runtime_error_count: int
    accepted: bool
    reasons: tuple[str, ...]


# ── Report construction ────────────────────────────────────────────────────


def build_eval_report(
    dataset: EvalDataset,
    *,
    runtime_mode: str,
    runtime_label: str,
    prompt_version: str,
    decision_observations: Sequence[DecisionObservation],
    full_turn_observations: Sequence[FullTurnObservation],
    runtime_metadata: Mapping[str, str] | None = None,
) -> EvalReport:
    """Build an eval report from frozen observations and dataset ground truth."""
    scenario_by_id = {case.scenario.scenario_id: case.scenario for case in dataset.cases}

    completeness = validate_completeness(dataset, decision_observations, full_turn_observations)

    metrics = _safe_metrics(
        dataset,
        decision_observations,
        runtime_label=runtime_label,
    )

    unauthorized = 0
    for observation in full_turn_observations:
        scenario = scenario_by_id.get(observation.scenario_id)
        if scenario is None:
            continue
        unauthorized += count_unauthorized_write_handler_executions(
            observation, scenario.expectation
        )

    safety = EvalSafetyResult(
        unauthorized_write_handler_execution_count=unauthorized,
        passed=unauthorized == 0,
    )

    quality = _evaluate_quality(dataset, metrics)

    sample_scores = _sample_scores(scenario_by_id, decision_observations, full_turn_observations)

    runtime_error_count = sum(
        1 for observation in full_turn_observations if observation.error_type is not None
    )

    reasons: list[str] = []
    reasons.extend(completeness.errors)
    if not safety.passed:
        reasons.append(f"unauthorized WRITE handler executions: {unauthorized}")
    if not quality.passed:
        reasons.append("false_write_tool_call_rate exceeds quality policy")
    if runtime_error_count:
        reasons.append(f"runtime errors: {runtime_error_count}")

    accepted = not reasons

    identity = EvalReportIdentity(
        report_schema_version=REPORT_SCHEMA_VERSION,
        dataset_id=dataset.dataset_id,
        dataset_version=dataset.dataset_version,
        dataset_fingerprint=dataset.fingerprint(),
        sample_plan_id=dataset.sample_plan.plan_id,
        sample_plan_fingerprint=dataset.sample_plan.fingerprint(),
        prompt_version=prompt_version,
    )

    runtime = EvalRuntimeInfo(
        mode=runtime_mode,
        label=runtime_label,
        metadata=tuple(sorted((runtime_metadata or {}).items())),
    )

    return EvalReport(
        identity=identity,
        runtime=runtime,
        sample_contract=completeness,
        decision_observations=tuple(decision_observations),
        full_turn_observations=tuple(full_turn_observations),
        metrics=tuple(metrics),
        sample_scores=tuple(sample_scores),
        safety=safety,
        quality=quality,
        runtime_error_count=runtime_error_count,
        accepted=accepted,
        reasons=tuple(reasons),
    )


def _safe_metrics(
    dataset: EvalDataset,
    observations: Sequence[DecisionObservation],
    *,
    runtime_label: str,
) -> list[MetricSummary]:
    """Summarize metrics, tolerating incomplete/duplicate observations.

    Filters unknown scenarios and de-duplicates by key so that a report can
    still be produced for an invalid run.  Completeness reports the anomalies.
    """
    scenario_by_id = {case.scenario.scenario_id: case.scenario for case in dataset.cases}
    seen: set[tuple[str, int]] = set()
    filtered: list[DecisionObservation] = []
    for observation in observations:
        if observation.scenario_id not in scenario_by_id:
            continue
        key = (observation.scenario_id, observation.repetition)
        if key in seen:
            continue
        seen.add(key)
        filtered.append(observation)
    return summarize_metrics(
        tuple(scenario_by_id.values()),
        filtered,
        runtime_label=runtime_label,
    )


def _evaluate_quality(
    dataset: EvalDataset,
    metrics: Sequence[MetricSummary],
) -> EvalQualityResult:
    threshold = dataset.quality_policy.max_false_write_tool_call_rate
    summary = next(
        (m for m in metrics if m.metric_id == MetricId.FALSE_WRITE_TOOL_CALL_RATE),
        None,
    )
    if summary is None:
        return EvalQualityResult(threshold, None, 0, 0, threshold is None)

    value = summary.value
    denominator = summary.denominator or 0
    if threshold is None:
        passed = True
    elif value is None:
        # No applicable samples (zero denominator): nothing can be violated.
        passed = True
    else:
        passed = value <= threshold
    return EvalQualityResult(
        max_false_write_tool_call_rate=threshold,
        false_write_rate_value=value,
        false_write_numerator=summary.numerator,
        false_write_denominator=denominator,
        passed=passed,
    )


def _sample_scores(
    scenario_by_id: Mapping[str, object],
    decision_observations: Sequence[DecisionObservation],
    full_turn_observations: Sequence[FullTurnObservation],
) -> list[EvalSampleScore]:
    from dnd_assistant.evals.contracts import EvalScenario

    decision_by_key = {(o.scenario_id, o.repetition): o for o in decision_observations}
    full_turn_by_key = {(o.scenario_id, o.repetition): o for o in full_turn_observations}
    keys = sorted(set(decision_by_key) | set(full_turn_by_key))

    scores: list[EvalSampleScore] = []
    for key in keys:
        scenario = scenario_by_id.get(key[0])
        decision_pass = False
        full_turn_pass = False
        if isinstance(scenario, EvalScenario):
            decision = decision_by_key.get(key)
            full_turn = full_turn_by_key.get(key)
            if decision is not None:
                decision_pass = score_decision(decision, scenario.expectation)
            if full_turn is not None:
                full_turn_pass = score_full_turn(full_turn, scenario.expectation)
        scores.append(
            EvalSampleScore(
                scenario_id=key[0],
                repetition=key[1],
                decision_pass=decision_pass,
                full_turn_pass=full_turn_pass,
            )
        )
    return scores


# ── Baseline comparison ────────────────────────────────────────────────────


class BaselineStatus(StrEnum):
    """Baseline compatibility classification."""

    COMPATIBLE = "compatible"
    INCOMPATIBLE = "incompatible"


@dataclass(frozen=True, slots=True)
class MetricDelta:
    """Per-metric baseline/current delta."""

    metric_id: MetricId
    baseline_value: float | None
    current_value: float | None
    delta: float | None
    baseline_numerator: int
    current_numerator: int
    baseline_denominator: int | None
    current_denominator: int | None


@dataclass(frozen=True, slots=True)
class BaselineComparison:
    """Result of comparing a current report against a baseline report."""

    status: BaselineStatus
    incompatible_reasons: tuple[str, ...]
    metric_deltas: tuple[MetricDelta, ...]
    safety_baseline: int
    safety_current: int
    quality_baseline_passed: bool
    quality_current_passed: bool


def compare_eval_reports(current: EvalReport, baseline: EvalReport) -> BaselineComparison:
    """Compare compatible reports; reject/classify incompatible ground truth."""
    reasons = _incompatibility_reasons(current, baseline)
    if reasons:
        return BaselineComparison(
            status=BaselineStatus.INCOMPATIBLE,
            incompatible_reasons=tuple(reasons),
            metric_deltas=(),
            safety_baseline=baseline.safety.unauthorized_write_handler_execution_count,
            safety_current=current.safety.unauthorized_write_handler_execution_count,
            quality_baseline_passed=baseline.quality.passed,
            quality_current_passed=current.quality.passed,
        )

    baseline_by_id = {m.metric_id: m for m in baseline.metrics}
    deltas: list[MetricDelta] = []
    for current_metric in current.metrics:
        baseline_metric = baseline_by_id.get(current_metric.metric_id)
        if baseline_metric is None:
            continue
        delta = None
        if current_metric.value is not None and baseline_metric.value is not None:
            delta = current_metric.value - baseline_metric.value
        deltas.append(
            MetricDelta(
                metric_id=current_metric.metric_id,
                baseline_value=baseline_metric.value,
                current_value=current_metric.value,
                delta=delta,
                baseline_numerator=baseline_metric.numerator,
                current_numerator=current_metric.numerator,
                baseline_denominator=baseline_metric.denominator,
                current_denominator=current_metric.denominator,
            )
        )

    return BaselineComparison(
        status=BaselineStatus.COMPATIBLE,
        incompatible_reasons=(),
        metric_deltas=tuple(deltas),
        safety_baseline=baseline.safety.unauthorized_write_handler_execution_count,
        safety_current=current.safety.unauthorized_write_handler_execution_count,
        quality_baseline_passed=baseline.quality.passed,
        quality_current_passed=current.quality.passed,
    )


def _incompatibility_reasons(current: EvalReport, baseline: EvalReport) -> list[str]:
    reasons: list[str] = []
    checks = (
        (
            "report_schema_version",
            current.identity.report_schema_version,
            baseline.identity.report_schema_version,
        ),
        ("dataset_id", current.identity.dataset_id, baseline.identity.dataset_id),
        ("dataset_version", current.identity.dataset_version, baseline.identity.dataset_version),
        (
            "dataset_fingerprint",
            current.identity.dataset_fingerprint,
            baseline.identity.dataset_fingerprint,
        ),
        ("sample_plan_id", current.identity.sample_plan_id, baseline.identity.sample_plan_id),
        (
            "sample_plan_fingerprint",
            current.identity.sample_plan_fingerprint,
            baseline.identity.sample_plan_fingerprint,
        ),
        ("prompt_version", current.identity.prompt_version, baseline.identity.prompt_version),
        (
            "expected_sample_count",
            current.sample_contract.expected_sample_count,
            baseline.sample_contract.expected_sample_count,
        ),
    )
    for name, current_value, baseline_value in checks:
        if current_value != baseline_value:
            reasons.append(f"{name} differs: current={current_value!r} baseline={baseline_value!r}")
    return reasons
