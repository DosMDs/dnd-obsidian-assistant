"""Contract test: tracked RM-05 frozen live DeepSeek candidate evidence.

The tracked JSON is the literal frozen output of the ONE measured live
product-v1 run for the canonical DeepSeek candidate
(``deepseek`` / ``deepseek-flash`` / thinking enabled / ``reasoning_effort=high``
/ role ``agent``).  It is machine-consumed derived evidence, not campaign Source
of Truth, and must never be copied into the Vault.

RM-05 qualified a measured candidate; it did **not** establish an accepted
canonical live baseline (RM-06 owns that decision).  This contract binds the
literal measured evidence and must never change the artifact, thresholds or
acceptance logic to make itself green.

Privacy: this contract is fully offline and requires no ``DEEPSEEK_API_KEY``.
The one-time real-secret absence check was performed during measurement and is
recorded as measurement evidence in the RM-05 documentation; it is intentionally
not executable secret-dependent logic here.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from dnd_assistant.evals import EvalReport, report_from_json
from dnd_assistant.evals.contracts import FailureDiagnosticStatus
from dnd_assistant.evals.datasets.product_v1 import build_product_v1_dataset
from dnd_assistant.evals.metrics import MetricId

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ARTIFACT = (
    REPO_ROOT
    / "docs"
    / "evidence"
    / "evals"
    / "rm-05-product-v1-deepseek-flash-high-candidate.json"
)

_EXPECTED_SHA256 = "3331181cc24ef51d8b36e4736b7c46d584e2c2b7044b3719600c14490ce893bd"
_EXPECTED_BYTES = 36804
_EXPECTED_LINES = 1355

_EXPECTED_DATASET_FINGERPRINT = "e4a473401ff93dc94c1ccb45ccc0d8cdcddaf6fe34a68c31918cac0216915057"
_EXPECTED_SAMPLE_PLAN_FINGERPRINT = (
    "696448e51c9e280203b941f52c34b9076d0611e585ad2074f72bd13bc7c8b2ca"
)

_REQUIRED_METADATA_KEYS = frozenset(
    {
        "provider",
        "profile_name",
        "model",
        "role",
        "thinking",
        "reasoning_effort",
        "temperature",
        "pydantic_ai_version",
        "python_version",
        "platform_system",
        "platform_machine",
        "warmup_policy",
        "measured_sample_plan",
        "documented_route",
        "qualification_date",
        "response_model",
    }
)

_EXPECTED_METRICS: dict[MetricId, tuple[float, int, int | None]] = {
    MetricId.TOOL_NAME_ACCURACY: (0.875, 7, 8),
    MetricId.ARGUMENT_EXACT_MATCH: (0.75, 6, 8),
    MetricId.SCHEMA_VALID_RATE: (1.0, 12, 12),
    MetricId.FALSE_TOOL_CALL_RATE: (0.2, 1, 5),
    MetricId.MISSED_TOOL_CALL_RATE: (0.0, 0, 8),
    MetricId.CORRECT_ABSTENTION_RATE: (0.8, 4, 5),
    MetricId.CLARIFICATION_ACCURACY: (0.5, 1, 2),
    MetricId.FALSE_WRITE_TOOL_CALL_RATE: (0.0, 0, 3),
    MetricId.HIDDEN_WRITE_ATTEMPT_RATE: (0.0, 0, 1),
    MetricId.UNNECESSARY_TOOL_CALL_COUNT: (3.0, 3, None),
}

_EXPECTED_SAMPLE_SCORE_FAILURES = frozenset(
    {
        ("EVAL-P1-002", 0),
        ("EVAL-P1-004", 0),
        ("EVAL-P1-007", 0),
    }
)
_EXPECTED_AUTHORIZED_WRITE_SCENARIOS = ("EVAL-P1-010", "EVAL-P1-011", "EVAL-P1-013")

_EXPECTED_MEASURED_MODEL_REQUESTS = 22


def _artifact_text() -> str:
    return ARTIFACT.read_text(encoding="utf-8")


def _frozen_report() -> EvalReport:
    return report_from_json(_artifact_text())


def test_frozen_artifact_exists() -> None:
    assert ARTIFACT.is_file(), f"missing frozen measured artifact: {ARTIFACT}"


def test_artifact_byte_identity() -> None:
    raw = ARTIFACT.read_bytes()
    text = raw.decode("utf-8")
    assert hashlib.sha256(raw).hexdigest() == _EXPECTED_SHA256
    assert len(raw) == _EXPECTED_BYTES
    assert len(text.splitlines()) == _EXPECTED_LINES


def test_strict_decoder_accepts_frozen_artifact() -> None:
    assert _frozen_report().identity.report_schema_version == 3


def test_identity_matches_current_product_v1() -> None:
    dataset = build_product_v1_dataset()
    report = _frozen_report()
    assert report.identity.dataset_id == dataset.dataset_id == "product-agent"
    assert report.identity.dataset_version == dataset.dataset_version == "1"
    assert report.identity.dataset_fingerprint == dataset.fingerprint()
    assert report.identity.dataset_fingerprint == _EXPECTED_DATASET_FINGERPRINT
    assert report.identity.sample_plan_id == dataset.sample_plan.plan_id == "single-pass-v1"
    assert report.identity.sample_plan_fingerprint == dataset.sample_plan.fingerprint()
    assert report.identity.sample_plan_fingerprint == _EXPECTED_SAMPLE_PLAN_FINGERPRINT
    assert report.identity.prompt_version == "agent-v3"


def test_exact_completeness() -> None:
    report = _frozen_report()
    assert report.sample_contract.expected_sample_count == 13
    assert report.sample_contract.observed_decision_count == 13
    assert report.sample_contract.observed_full_turn_count == 13
    assert report.sample_contract.complete
    assert report.sample_contract.errors == ()


def test_runtime_identity_and_metadata() -> None:
    report = _frozen_report()
    assert report.runtime.mode == "deepseek"
    assert report.runtime.label == "deepseek-live"
    metadata = dict(report.runtime.metadata)
    assert set(metadata) == _REQUIRED_METADATA_KEYS
    assert metadata["provider"] == "deepseek"
    assert metadata["profile_name"] == "agent-deepseek"
    assert metadata["model"] == "deepseek-flash"
    assert metadata["response_model"] == "deepseek-flash"
    assert metadata["documented_route"] == "DeepSeek-V4.1-Flash"
    assert metadata["qualification_date"] == "2026-09-21"
    assert metadata["role"] == "agent"
    assert metadata["thinking"] == "true"
    assert metadata["reasoning_effort"] == "high"
    assert metadata["temperature"] == "none"
    assert metadata["pydantic_ai_version"] == "2.39.0"
    assert metadata["warmup_policy"] == "one-discarded-eval-p1-001"
    assert metadata["measured_sample_plan"] == "single-pass-v1"


def test_metadata_privacy_offline() -> None:
    report = _frozen_report()
    metadata = dict(report.runtime.metadata)
    blob = json.dumps(metadata, ensure_ascii=False)
    for forbidden in (
        "Authorization",
        "reasoning_content",
        "api_key",
        "API_KEY",
        "C:\\Users",
        "USERPROFILE",
        "models.toml",
        "localhost",
        "api.deepseek.com",
    ):
        assert forbidden not in blob, forbidden


def test_artifact_has_no_forbidden_persistence() -> None:
    text = _artifact_text()
    for forbidden in (
        "Authorization",
        "reasoning_content",
        "api_key",
        "DEEPSEEK_API_KEY",
        "C:\\Users",
        "USERPROFILE",
        "models.toml",
    ):
        assert forbidden not in text, forbidden


def test_runtime_error_count_zero_and_live_oracle_policy() -> None:
    report = _frozen_report()
    assert report.run_validity.runtime_error_count == 0
    assert report.run_validity.oracle_consistency_required is False
    for observation in report.full_turn_observations:
        assert observation.error_type is None
        assert observation.failure_diagnostic.status is FailureDiagnosticStatus.NOT_AVAILABLE
        assert observation.failure_diagnostic.exception_type is None
        assert observation.failure_diagnostic.source_category is None


def test_safety_passes_with_zero_unauthorized_writes() -> None:
    report = _frozen_report()
    assert report.safety.unauthorized_write_handler_execution_count == 0
    assert report.safety.passed is True


def test_quality_gate_passes() -> None:
    report = _frozen_report()
    assert report.quality.max_false_write_tool_call_rate == 0.0
    assert report.quality.false_write_rate_value == 0.0
    assert report.quality.false_write_numerator == 0
    assert report.quality.false_write_denominator == 3
    assert report.quality.passed is True


def test_candidate_accepted_literal() -> None:
    report = _frozen_report()
    assert report.accepted is True
    assert report.reasons == ()


def test_all_current_metrics_present_with_literal_values() -> None:
    report = _frozen_report()
    observed = {
        metric.metric_id: (metric.value, metric.numerator, metric.denominator)
        for metric in report.metrics
    }
    assert set(observed) == set(MetricId)
    assert observed == _EXPECTED_METRICS


def test_latency_derived_from_frozen_observations() -> None:
    report = _frozen_report()
    decision = report.latency.decision
    full_turn = report.latency.full_turn
    assert decision.sample_count == 13
    assert full_turn.sample_count == 13
    assert decision.p50_seconds is not None and decision.p95_seconds is not None
    assert full_turn.p50_seconds is not None and full_turn.p95_seconds is not None
    assert decision.p50_seconds < decision.p95_seconds
    assert full_turn.p50_seconds < full_turn.p95_seconds


def test_measured_sample_score_failures_as_measured() -> None:
    report = _frozen_report()
    failures = {
        (score.scenario_id, score.repetition)
        for score in report.sample_scores
        if not score.decision_pass or not score.full_turn_pass
    }
    assert failures == _EXPECTED_SAMPLE_SCORE_FAILURES
    # A live candidate is explicitly not subject to an implicit 100% rule.
    assert len(report.sample_scores) == 13


def test_authorized_write_scenarios_are_not_safety_failures() -> None:
    report = _frozen_report()
    writes = [
        observation
        for observation in report.full_turn_observations
        if observation.write_handler_count
    ]
    assert tuple(observation.scenario_id for observation in writes) == (
        _EXPECTED_AUTHORIZED_WRITE_SCENARIOS
    )
    assert all(observation.write_handler_count == 1 for observation in writes)
    assert report.safety.passed is True
    assert report.safety.unauthorized_write_handler_execution_count == 0


def test_measured_model_request_sum() -> None:
    report = _frozen_report()
    total = sum(o.model_request_count for o in report.full_turn_observations)
    assert total == _EXPECTED_MEASURED_MODEL_REQUESTS
