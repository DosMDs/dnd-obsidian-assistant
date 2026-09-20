"""Provider-neutral versioned eval dataset contract.

This module defines the dataset DTOs used by the product eval runner: explicit
per-case execution metadata (authority + session state), the quality policy,
the sample plan and deterministic dataset/sample-plan fingerprints.

It belongs to ``dnd_assistant.evals`` and imports the Python standard library
and this package only.  It must never import another ``dnd_assistant`` layer,
Ollama, Pydantic AI, Textual, Typer or any concrete model/provider, and must
perform no filesystem or network access at import time.

The dataset is versioned repository source (ground truth), not campaign Truth.
Fingerprints are computed over stable contract data only: they never include
runtime timing, transient values or human editorial wording.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from dnd_assistant.evals.contracts import EvalScenario, ScenarioExpectationKind

# ── Execution metadata vocabulary ──────────────────────────────────────────


class EvalPermission(StrEnum):
    """Model-facing execution authority for one eval case.

    Local to the provider-neutral eval package; the composition layer maps it
    to the trusted ``dnd_assistant.tools.types.Permission`` enum.  It exists
    here so the dataset does not depend on the Tool Layer.
    """

    READ = "read"
    WRITE = "write"


class EvalSessionState(StrEnum):
    """Session-mode fixture variant for one eval case."""

    NO_ACTIVE = "no_active_session"
    ACTIVE = "active_session"


@dataclass(frozen=True, slots=True)
class EvalExecutionSpec:
    """Explicit execution context for one eval case.

    Args:
        permission: Granted model-facing authority.
        session_state: Whether the synthetic fixture starts with an active
            session.
    """

    permission: EvalPermission
    session_state: EvalSessionState


# ── Dataset DTOs ───────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class EvalQualityPolicy:
    """Product quality policy frozen by the dataset.

    Args:
        max_false_write_tool_call_rate: Acceptance ceiling for the existing
            ``FALSE_WRITE_TOOL_CALL_RATE`` metric.  ``None`` means report-only
            (no live quality gate yet).  ``0.0`` is a product-quality gate, not
            the system-safety invariant.
    """

    max_false_write_tool_call_rate: float | None = 0.0


@dataclass(frozen=True, slots=True)
class EvalCase:
    """One eval case = scenario ground truth + execution metadata.

    Args:
        scenario: The deterministic expectation (S14-02 vocabulary).
        execution: Explicit authority/session fixture selection.
    """

    scenario: EvalScenario
    execution: EvalExecutionSpec


@dataclass(frozen=True, slots=True)
class EvalSamplePlan:
    """Versioned sample policy.

    Args:
        plan_id: Stable plan identifier.
        repetitions: Number of samples per scenario, run from fresh state.
    """

    plan_id: str
    repetitions: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.plan_id, str) or not self.plan_id.strip():
            raise ValueError("plan_id must be a non-empty string")
        if self.plan_id.strip() != self.plan_id:
            raise ValueError("plan_id must not have leading or trailing whitespace")
        if not isinstance(self.repetitions, int) or isinstance(self.repetitions, bool):
            raise ValueError("repetitions must be an int")
        if self.repetitions < 1:
            raise ValueError("repetitions must be >= 1")

    def fingerprint(self) -> str:
        """Deterministic SHA-256 fingerprint of the sample plan."""
        return _sha256_json({"plan_id": self.plan_id, "repetitions": self.repetitions})


@dataclass(frozen=True, slots=True)
class EvalDataset:
    """Versioned product eval dataset.

    Args:
        dataset_id: Stable dataset identifier.
        dataset_version: Version string within the dataset identity.
        cases: Ordered eval cases.
        quality_policy: Product quality policy bound to this dataset.
        sample_plan: Versioned sample policy used to expand the dataset.
    """

    dataset_id: str
    dataset_version: str
    cases: tuple[EvalCase, ...]
    quality_policy: EvalQualityPolicy = field(default_factory=EvalQualityPolicy)
    sample_plan: EvalSamplePlan = field(default_factory=lambda: EvalSamplePlan("single-pass-v1"))

    def __post_init__(self) -> None:
        if not isinstance(self.dataset_id, str) or not self.dataset_id.strip():
            raise ValueError("dataset_id must be a non-empty string")
        if not isinstance(self.dataset_version, str) or not self.dataset_version.strip():
            raise ValueError("dataset_version must be a non-empty string")
        if not self.cases:
            raise ValueError("dataset must contain at least one case")
        if not isinstance(self.cases, tuple):
            raise ValueError("cases must be a tuple")

        seen: set[str] = set()
        for case in self.cases:
            if not isinstance(case, EvalCase):
                raise ValueError("every dataset case must be an EvalCase")
            scenario_id = case.scenario.scenario_id
            if scenario_id in seen:
                raise ValueError(f"duplicate scenario_id in dataset: {scenario_id!r}")
            seen.add(scenario_id)
            _validate_case(case)

    @property
    def scenario_ids(self) -> tuple[str, ...]:
        """Scenario IDs in dataset order."""
        return tuple(case.scenario.scenario_id for case in self.cases)

    def expected_sample_count(self) -> int:
        """Total expected samples (cases x repetitions)."""
        return len(self.cases) * self.sample_plan.repetitions

    def fingerprint(self) -> str:
        """Deterministic SHA-256 fingerprint of the dataset contract.

        Includes semantic ground truth (scenario id/input/expectation,
        execution metadata, quality policy).  Excludes human-only descriptions.
        """
        payload: dict[str, Any] = {
            "dataset_id": self.dataset_id,
            "dataset_version": self.dataset_version,
            "quality_policy": {
                "max_false_write_tool_call_rate": self.quality_policy.max_false_write_tool_call_rate,
            },
            "cases": [_case_payload(case) for case in self.cases],
        }
        return _sha256_json(payload)


# ── Validation ─────────────────────────────────────────────────────────────


def _validate_case(case: EvalCase) -> None:
    scenario = case.scenario
    if not isinstance(scenario.scenario_id, str) or not scenario.scenario_id.strip():
        raise ValueError("scenario_id must be a non-empty string")
    if not isinstance(scenario.user_input, str) or not scenario.user_input.strip():
        raise ValueError(f"scenario {scenario.scenario_id!r}: user_input must be non-empty")

    expectation = scenario.expectation
    if expectation.kind == ScenarioExpectationKind.EXACT_TOOL_CALLS:
        if not expectation.tool_calls:
            raise ValueError(
                f"scenario {scenario.scenario_id!r}: EXACT_TOOL_CALLS requires at least one call"
            )
    elif expectation.tool_calls:
        raise ValueError(
            f"scenario {scenario.scenario_id!r}: no-tool expectations must not declare tool calls"
        )

    if scenario.hidden_write_expected and case.execution.permission == EvalPermission.WRITE:
        raise ValueError(
            f"scenario {scenario.scenario_id!r}: hidden_write_expected requires READ authority"
        )


# ── Canonical serialization ────────────────────────────────────────────────


def _case_payload(case: EvalCase) -> dict[str, Any]:
    scenario = case.scenario
    expectation = scenario.expectation
    return {
        "scenario_id": scenario.scenario_id,
        "user_input": scenario.user_input,
        "expectation_kind": expectation.kind.value,
        "order_sensitive": expectation.order_sensitive,
        "hidden_write_expected": scenario.hidden_write_expected,
        "execution": {
            "permission": case.execution.permission.value,
            "session_state": case.execution.session_state.value,
        },
        "tool_calls": [
            {
                "tool_name": call.tool_name,
                "arguments": call.arguments,
                "is_write": call.is_write,
            }
            for call in expectation.tool_calls
        ],
    }


def _sha256_json(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
