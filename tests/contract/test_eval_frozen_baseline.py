"""Contract test: tracked S14-07 frozen measured live Ollama evidence.

The tracked JSON is the literal frozen output of the ONE measured live
product-v1 run (S14-07). It is machine-consumed derived evidence, not campaign
Source of Truth, and must never be copied into the Vault.

This contract binds the artifact's structural/identity invariants and its
literal recorded candidate outcome. Removing or replacing the artifact without
updating this contract must fail.
"""

from __future__ import annotations

import json
from pathlib import Path

from dnd_assistant.evals import EvalReport, report_from_json
from dnd_assistant.evals.datasets.product_v1 import build_product_v1_dataset
from dnd_assistant.evals.metrics import MetricId

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
ARTIFACT = REPO_ROOT / "docs" / "evidence" / "evals" / "s14-07-product-v1-ollama-baseline.json"

_EXPECTED_RUNTIME_ERRORS = 2
_EXPECTED_ERROR_SCENARIOS = frozenset({"EVAL-P1-007", "EVAL-P1-009"})
_REQUIRED_METADATA_KEYS = frozenset(
    {
        "provider",
        "profile_name",
        "model",
        "role",
        "temperature",
        "keep_alive",
        "pydantic_ai_version",
        "ollama_server_version",
        "python_version",
        "platform_system",
        "platform_machine",
        "warmup_policy",
        "measured_sample_plan",
    }
)


def _frozen_report() -> EvalReport:
    return report_from_json(ARTIFACT.read_text(encoding="utf-8"))


def test_frozen_artifact_exists() -> None:
    assert ARTIFACT.is_file(), f"missing frozen measured artifact: {ARTIFACT}"


def test_strict_decoder_accepts_frozen_artifact() -> None:
    assert _frozen_report().identity.report_schema_version == 2


def test_identity_matches_current_product_v1() -> None:
    dataset = build_product_v1_dataset()
    report = _frozen_report()
    assert report.identity.dataset_id == dataset.dataset_id
    assert report.identity.dataset_version == dataset.dataset_version
    assert report.identity.dataset_fingerprint == dataset.fingerprint()
    assert report.identity.sample_plan_id == dataset.sample_plan.plan_id
    assert report.identity.sample_plan_fingerprint == dataset.sample_plan.fingerprint()
    assert report.identity.prompt_version == "agent-v3"


def test_exact_completeness() -> None:
    report = _frozen_report()
    assert report.sample_contract.expected_sample_count == 13
    assert report.sample_contract.observed_decision_count == 13
    assert report.sample_contract.observed_full_turn_count == 13
    assert report.sample_contract.complete


def test_runtime_identity_and_metadata_privacy() -> None:
    report = _frozen_report()
    assert report.runtime.mode == "ollama"
    assert report.runtime.label == "ollama-live"
    metadata = dict(report.runtime.metadata)
    assert set(metadata) == _REQUIRED_METADATA_KEYS
    blob = json.dumps(metadata, ensure_ascii=False)
    for forbidden in ("C:", "localhost", "endpoint", "USERPROFILE", "models.toml"):
        assert forbidden not in blob, forbidden


def test_safety_and_false_write_quality_gate() -> None:
    report = _frozen_report()
    assert report.safety.unauthorized_write_handler_execution_count == 0
    assert report.safety.passed
    assert report.quality.false_write_numerator == 0
    assert report.quality.false_write_denominator == 3
    assert report.quality.false_write_rate_value == 0.0
    assert report.quality.passed


def test_all_current_metrics_present() -> None:
    report = _frozen_report()
    assert {metric.metric_id for metric in report.metrics} == set(MetricId)


def test_latency_derived_from_frozen_observations() -> None:
    report = _frozen_report()
    decision = report.latency.decision
    full_turn = report.latency.full_turn
    assert decision.sample_count == 13
    assert full_turn.sample_count == 13
    layers = (
        (decision.p50_seconds, decision.p95_seconds),
        (full_turn.p50_seconds, full_turn.p95_seconds),
    )
    for p50, p95 in layers:
        assert p50 is not None and p95 is not None
        assert p50 >= 0.0 and p95 >= 0.0
        assert p50 <= p95


def test_literal_recorded_candidate_outcome() -> None:
    report = _frozen_report()
    assert report.run_validity.runtime_error_count == _EXPECTED_RUNTIME_ERRORS
    assert report.accepted is False
    errored = {
        observation.scenario_id
        for observation in report.full_turn_observations
        if observation.error_type is not None
    }
    assert errored == _EXPECTED_ERROR_SCENARIOS
