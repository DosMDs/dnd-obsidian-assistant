"""PAIM-13: Eval comparison — Layer A decision quality tests.

Compares reference (FastAgent) vs candidate (PydanticAIFastAgent)
first-decision quality across 18 scenarios × 3 repetitions.

Requires environment variables:

    DND_ASSISTANT_PAIM13_CONFIG=<path-to-models.toml>
    DND_ASSISTANT_PAIM13_AGENT_PROFILE=<profile-name>

When ``DND_ASSISTANT_PAIM13_CONFIG`` is absent, all tests skip before
any network request.
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any

import pytest

from dnd_assistant.application.fast_agent import FastAgent
from dnd_assistant.application.pydantic_ai_fast_agent import (
    PydanticAIFastAgent,
)
from dnd_assistant.application.pydantic_ai_run_deps import (
    DndAgentRunPreparer,
)
from dnd_assistant.application.pydantic_ai_tool_bridge import (
    PydanticAIToolBridge,
)
from dnd_assistant.errors import ModelError
from dnd_assistant.models.ollama import OllamaModelProvider
from dnd_assistant.models.profiles import (
    ModelProfile,
    ModelProfileRole,
    load_model_profiles,
)
from dnd_assistant.models.pydantic_ai_ollama import (
    build_pydantic_ai_ollama_model,
)
from dnd_assistant.tools.catalog import build_tool_registry_schema
from dnd_assistant.tools.types import (
    ExecutionContext,
)
from tests.support.paim13_live_harness import (
    CountingModelGateway,
    CountingPydanticModel,
    build_eval_registry,
    make_deterministic_context_builder,
    parse_terminal_observation,
)
from tests.support.paim13_scenarios import (
    DECISION_SCENARIOS,
    EvalHandlerState,
    check_schema_valid,
    get_context_for_scenario,
    make_read_context,
)
from tests.support.pydantic_ai_eval import (
    DecisionObservation,
    EvalScenario,
    ExposedToolInfo,
    ScenarioComparison,
    ScenarioExpectationKind,
    ToolCallObservation,
    classify_majority,
    nearest_rank_percentile,
    score_decision,
    summarize_metrics,
)
from tests.support.pydantic_ai_eval_datasets import FrozenDecisionDataset

pytestmark = pytest.mark.ollama

# ── Environment variable names ────────────────────────────────────────────────

ENV_CONFIG = "DND_ASSISTANT_PAIM13_CONFIG"
ENV_PROFILE = "DND_ASSISTANT_PAIM13_AGENT_PROFILE"


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.fail(
            f"Explicit PAIM-13 opt-in detected ({ENV_CONFIG} is set), "
            f"but required variable {name} is missing or empty."
        )
    return value


@pytest.fixture(scope="module")
def paim13_config() -> tuple[ModelProfile, str, str]:
    """Load the PAIM-13 model profile from environment configuration."""
    config_path = os.environ.get(ENV_CONFIG)
    if not config_path:
        pytest.skip(
            f"PAIM-13 live eval requires {ENV_CONFIG}. "
            "Set this environment variable to run real-Ollama comparison."
        )

    profile_name = _require_env(ENV_PROFILE)
    config = load_model_profiles(Path(config_path))
    profile = config.profiles.get(profile_name)
    if profile is None:
        pytest.fail(
            f"Profile {profile_name!r} not found in {config_path}. "
            f"Available profiles: {list(config.profiles)}"
        )

    if profile.provider != "ollama":
        pytest.fail(f"PAIM-13 requires provider='ollama', got {profile.provider!r}")
    if profile.role is not ModelProfileRole.AGENT:
        pytest.fail(f"PAIM-13 requires role=AGENT, got {profile.role!r}")
    if profile.keep_alive is not None:
        pytest.fail(f"PAIM-13 requires keep_alive=None, got {profile.keep_alive!r}")

    native = OllamaModelProvider(profile)
    try:
        version = native.version()
        model_name = profile.model
    except Exception as exc:
        pytest.fail(f"Failed to connect to Ollama at {profile.base_url}: {exc}")
    finally:
        native.close()

    return profile, model_name, version


@pytest.fixture(scope="module")
def reference_runtime(paim13_config):
    """Build the reference decision runtime.

    Reference path:
        OllamaModelProvider(profile)
        -> CountingModelGateway
        -> FastAgent
    """
    profile, model_name, _ = paim13_config

    ref_state = EvalHandlerState()
    ref_registry = build_eval_registry(ref_state)
    ref_catalog = build_tool_registry_schema(ref_registry)
    ref_context_builder = make_deterministic_context_builder()

    native_provider = OllamaModelProvider(profile)
    counting_gateway = CountingModelGateway(native_provider)

    ref_fast_agent = FastAgent(
        context_builder=ref_context_builder,
        model_gateway=counting_gateway,
        tool_catalog=ref_catalog,
    )

    yield {
        "fast_agent": ref_fast_agent,
        "state": ref_state,
        "registry": ref_registry,
        "counting_gateway": counting_gateway,
        "native_provider": native_provider,
        "profile": profile,
    }

    native_provider.close()


@pytest.fixture(scope="module")
def candidate_runtime(paim13_config):
    """Build the candidate decision runtime.

    Candidate path:
        build_pydantic_ai_ollama_model(profile)
        -> CountingPydanticModel wrapper
        -> PydanticAIFastAgent
        -> DndAgentRunPreparer
        -> PydanticAIToolBridge
        -> ToolExecutor
    """
    profile, model_name, _ = paim13_config

    cand_state = EvalHandlerState()
    cand_registry = build_eval_registry(cand_state)
    cand_catalog = build_tool_registry_schema(cand_registry)
    cand_context_builder = make_deterministic_context_builder()

    cand_tool_bridge = PydanticAIToolBridge(cand_registry)
    cand_preparer = DndAgentRunPreparer(
        context_builder=cand_context_builder,
        tool_catalog=cand_catalog,
        tool_bridge=cand_tool_bridge,
    )

    real_model = build_pydantic_ai_ollama_model(profile)
    counting_model = CountingPydanticModel(real_model)

    cand_fast_agent = PydanticAIFastAgent(
        run_preparer=cand_preparer,
        model=counting_model,
    )

    yield {
        "fast_agent": cand_fast_agent,
        "state": cand_state,
        "registry": cand_registry,
        "preparer": cand_preparer,
        "counting_model": counting_model,
        "profile": profile,
    }


# ── Frozen dataset fixture (warm-up + collection exactly once) ────────────────


def _warmup(runtime: dict[str, Any]) -> None:
    """Perform one warm-up decision on each runtime (excluded from metrics).

    Warm-up failure must fail fixture construction — exceptions are not
    swallowed.
    """
    context = make_read_context()
    runtime["fast_agent"].decide(
        "Hello, this is a warm-up request.",
        execution_context=context,
    )


@pytest.fixture(scope="module")
def frozen_decision_dataset(
    reference_runtime,
    candidate_runtime,
) -> FrozenDecisionDataset:
    """Collect all Layer A observations exactly once with warm-up first.

    Warm-up runs before any measured observation.  The returned dataset
    is consumed by scenario tests and aggregate metrics — no additional
    model calls.
    """
    ref_runtime = reference_runtime
    cand_runtime = candidate_runtime

    # Warm-up before measurement (excluded from all metrics)
    _warmup(ref_runtime)
    _warmup(cand_runtime)

    ref_observations: list[DecisionObservation] = []
    cand_observations: list[DecisionObservation] = []

    for scenario in DECISION_SCENARIOS:
        context = get_context_for_scenario(scenario.scenario_id)
        for rep in range(3):
            if rep % 2 == 0:
                ref_obs = _observe_reference_decision(scenario, rep, ref_runtime, context)
                cand_obs = _observe_candidate_decision(scenario, rep, cand_runtime, context)
            else:
                cand_obs = _observe_candidate_decision(scenario, rep, cand_runtime, context)
                ref_obs = _observe_reference_decision(scenario, rep, ref_runtime, context)
            ref_observations.append(ref_obs)
            cand_observations.append(cand_obs)

    return FrozenDecisionDataset(
        scenarios=tuple(DECISION_SCENARIOS),
        reference_observations=tuple(ref_observations),
        candidate_observations=tuple(cand_observations),
    )


# ── Layer A: Reference decision observer ──────────────────────────────────────


def _observe_reference_decision(
    scenario: EvalScenario,
    repetition: int,
    runtime: dict[str, Any],
    context: ExecutionContext,
) -> DecisionObservation:
    """Observe one decision from the reference FastAgent (Layer A)."""
    fast_agent: FastAgent = runtime["fast_agent"]

    start = time.perf_counter()
    error_type: str | None = None
    error_message: str | None = None
    tool_calls: tuple[ToolCallObservation, ...] = ()
    terminal_kind: str | None = None
    exposed_info: ExposedToolInfo | None = None

    try:
        decision = fast_agent.decide(
            scenario.user_input,
            execution_context=context,
        )

        response = decision.response
        exposed_names = tuple(t.name for t in decision.exposed_tools)
        has_write = any(t.permission.value == "write" for t in decision.exposed_tools)
        exposed_info = ExposedToolInfo(tool_names=exposed_names, has_write=has_write)

        observed_calls: list[ToolCallObservation] = []
        for tc in response.message.tool_calls:
            schema_valid = check_schema_valid(
                tc.tool_name,
                tc.arguments,
                exposed_tool_names=exposed_names,
            )
            observed_calls.append(
                ToolCallObservation(
                    tool_name=tc.tool_name,
                    arguments=tc.arguments,
                    call_id=tc.call_id,
                    schema_valid=schema_valid,
                )
            )
        tool_calls = tuple(observed_calls)

        # Parse terminal outcome — never convert parse failures to CLARIFY
        terminal_kind = parse_terminal_observation(response, tool_calls)
        if terminal_kind is None and not tool_calls:
            # Parse failed: mark as error
            error_type = "ParseError"
            error_message = "Failed to parse terminal outcome from response"

    except ModelError as exc:
        error_type = "ModelError"
        error_message = str(exc)
    except Exception as exc:
        error_type = type(exc).__name__
        error_message = str(exc)

    duration = time.perf_counter() - start

    return DecisionObservation(
        scenario_id=scenario.scenario_id,
        repetition=repetition,
        duration_seconds=duration,
        tool_calls=tool_calls,
        terminal_kind=terminal_kind,
        terminal_content=None,
        exposed_tools=exposed_info,
        error_type=error_type,
        error_message=error_message,
    )


# ── Layer A: Candidate decision observer ──────────────────────────────────────


def _observe_candidate_decision(
    scenario: EvalScenario,
    repetition: int,
    runtime: dict[str, Any],
    context: ExecutionContext,
) -> DecisionObservation:
    """Observe one decision from the candidate PydanticAIFastAgent (Layer A)."""
    fast_agent: PydanticAIFastAgent = runtime["fast_agent"]

    start = time.perf_counter()
    error_type: str | None = None
    error_message: str | None = None
    tool_calls: tuple[ToolCallObservation, ...] = ()
    terminal_kind: str | None = None
    exposed_info: ExposedToolInfo | None = None

    try:
        decision = fast_agent.decide(
            scenario.user_input,
            execution_context=context,
        )

        response = decision.response
        exposed_names = tuple(t.name for t in decision.exposed_tools)
        has_write = any(t.permission.value == "write" for t in decision.exposed_tools)
        exposed_info = ExposedToolInfo(tool_names=exposed_names, has_write=has_write)

        observed_calls: list[ToolCallObservation] = []
        for tc in response.message.tool_calls:
            schema_valid = check_schema_valid(
                tc.tool_name,
                tc.arguments,
                exposed_tool_names=exposed_names,
            )
            observed_calls.append(
                ToolCallObservation(
                    tool_name=tc.tool_name,
                    arguments=tc.arguments,
                    call_id=tc.call_id,
                    schema_valid=schema_valid,
                )
            )
        tool_calls = tuple(observed_calls)

        # Parse terminal outcome — never convert parse failures to CLARIFY
        terminal_kind = parse_terminal_observation(response, tool_calls)
        if terminal_kind is None and not tool_calls:
            error_type = "ParseError"
            error_message = "Failed to parse terminal outcome from response"

    except ModelError as exc:
        error_type = "ModelError"
        error_message = str(exc)
    except Exception as exc:
        error_type = type(exc).__name__
        error_message = str(exc)

    duration = time.perf_counter() - start

    return DecisionObservation(
        scenario_id=scenario.scenario_id,
        repetition=repetition,
        duration_seconds=duration,
        tool_calls=tool_calls,
        terminal_kind=terminal_kind,
        terminal_content=None,
        exposed_tools=exposed_info,
        error_type=error_type,
        error_message=error_message,
    )


# ==============================================================================
# Layer A — Decision quality tests
# ==============================================================================


class TestPaim13DecisionEval:
    """First-decision quality comparison (Layer A).

    Compares reference (FastAgent) vs candidate (PydanticAIFastAgent)
    first-decision tool selection, argument generation, schema validity,
    clarification, false WRITE selection, unnecessary calls, and abstention.

    All observations come from the frozen dataset — no additional model calls.
    """

    @pytest.mark.parametrize("scenario", DECISION_SCENARIOS, ids=lambda s: s.scenario_id)
    def test_decision_scenario(
        self,
        scenario: EvalScenario,
        frozen_decision_dataset: FrozenDecisionDataset,
    ) -> None:
        """Score one decision scenario from the frozen dataset."""
        ref_observations = [
            o
            for o in frozen_decision_dataset.reference_observations
            if o.scenario_id == scenario.scenario_id
        ]
        cand_observations = [
            o
            for o in frozen_decision_dataset.candidate_observations
            if o.scenario_id == scenario.scenario_id
        ]

        # Score and classify
        ref_passes = sum(1 for o in ref_observations if score_decision(o, scenario.expectation))
        cand_passes = sum(1 for o in cand_observations if score_decision(o, scenario.expectation))

        ref_majority = ref_passes >= 2
        cand_majority = cand_passes >= 2

        # Print compact result
        print(
            f"\nPAIM13_SCENARIO {scenario.scenario_id}"
            f"\nREF={ref_passes}/3 majority={'PASS' if ref_majority else 'FAIL'}"
            f"\nPYD={cand_passes}/3 majority={'PASS' if cand_majority else 'FAIL'}"
        )

        # Critical-regression enforcement:
        # REFERENCE_ONLY_PASS for a critical scenario must fail pytest
        if scenario.critical_regression and ref_majority and not cand_majority:
            pytest.fail(
                f"Critical regression in {scenario.scenario_id}: "
                f"reference passes ({ref_passes}/3) but candidate fails ({cand_passes}/3). "
                f"This is a REFERENCE_ONLY_PASS for a critical scenario."
            )

        # Assert no false WRITE in candidate
        for obs in cand_observations:
            for tc in obs.tool_calls:
                if tc.tool_name.startswith("write_"):
                    is_write_expected = (
                        scenario.expectation.kind == ScenarioExpectationKind.EXACT_TOOL_CALLS
                        and any(
                            e.tool_name.startswith("write_")
                            for e in scenario.expectation.tool_calls
                        )
                    )
                    if not is_write_expected:
                        pytest.fail(
                            f"Candidate false WRITE call in {scenario.scenario_id}: "
                            f"{tc.tool_name}({tc.arguments})"
                        )


# ── Metric labels ─────────────────────────────────────────────────────────────

_METRIC_LABELS = {
    0: "SCENARIO_SUCCESS",
    1: "TOOL_NAME_ACCURACY",
    2: "ARGUMENT_EXACT",
    3: "SCHEMA_VALID",
    4: "FALSE_TOOL_CALL",
    5: "MISSED_TOOL_CALL",
    6: "CORRECT_ABSTENTION",
    7: "CLARIFICATION",
    8: "FALSE_WRITE",
    9: "HIDDEN_WRITE",
    10: "UNNECESSARY_CALLS",
}


# ==============================================================================
# Aggregate metrics
# ==============================================================================


class TestPaim13AggregateMetrics:
    """Compute and report aggregate metrics across all scenarios.

    All values derived from the frozen dataset — no additional model calls.
    """

    def test_report_aggregate_metrics(
        self,
        frozen_decision_dataset: FrozenDecisionDataset,
        paim13_config,
    ) -> None:
        profile, model_name, ollama_version = paim13_config
        all_ref_observations = list(frozen_decision_dataset.reference_observations)
        all_cand_observations = list(frozen_decision_dataset.candidate_observations)
        ref_metrics = summarize_metrics(DECISION_SCENARIOS, all_ref_observations, "reference")
        cand_metrics = summarize_metrics(DECISION_SCENARIOS, all_cand_observations, "candidate")
        ref_decision_times = sorted(o.duration_seconds for o in all_ref_observations)
        cand_decision_times = sorted(o.duration_seconds for o in all_cand_observations)
        ref_p50 = nearest_rank_percentile(ref_decision_times, 50)
        ref_p95 = nearest_rank_percentile(ref_decision_times, 95)
        cand_p50 = nearest_rank_percentile(cand_decision_times, 50)
        cand_p95 = nearest_rank_percentile(cand_decision_times, 95)
        print(f"\nPAIM13_MODEL={model_name}")
        print(f"PAIM13_OLLAMA_VERSION={ollama_version}")
        print(f"PAIM13_SCENARIO_COUNT={len(DECISION_SCENARIOS)}")
        print("PAIM13_REPETITIONS=3")

        # Build scenario comparisons once — used for both console output
        # and critical-regression enforcement.
        scenario_comparisons: list[ScenarioComparison] = []
        for scenario in DECISION_SCENARIOS:
            ref_scenario_obs = [
                o for o in all_ref_observations if o.scenario_id == scenario.scenario_id
            ]
            cand_scenario_obs = [
                o for o in all_cand_observations if o.scenario_id == scenario.scenario_id
            ]
            comp = classify_majority(
                scenario.scenario_id, ref_scenario_obs, cand_scenario_obs, scenario.expectation
            )
            scenario_comparisons.append(
                ScenarioComparison(
                    scenario_id=scenario.scenario_id,
                    classification=comp.classification,
                    reference_passes=comp.reference_passes,
                    candidate_passes=comp.candidate_passes,
                    critical_regression=scenario.critical_regression,
                )
            )
            print(
                f"PAIM13_SCENARIO {comp.scenario_id} REF={comp.reference_passes}/3 PYD={comp.candidate_passes}/3 class={comp.classification}"
            )

        # Critical-regression enforcement from same comparisons:
        # REFERENCE_ONLY_PASS for a critical scenario must fail pytest.
        for sc in scenario_comparisons:
            if sc.critical_regression and sc.classification == "REFERENCE_ONLY_PASS":
                pytest.fail(
                    f"Critical regression in {sc.scenario_id}: "
                    f"REFERENCE_ONLY_PASS for a critical scenario. "
                    f"Reference {sc.reference_passes}/3, candidate {sc.candidate_passes}/3."
                )

        for index, (ref_m, cand_m) in enumerate(zip(ref_metrics, cand_metrics, strict=True)):
            label = _METRIC_LABELS[index]
            delta = cand_m.value - ref_m.value
            print(f"PAIM13_REF_{label}={ref_m.value:.4f} ({ref_m.numerator}/{ref_m.denominator})")
            print(
                f"PAIM13_PYD_{label}={cand_m.value:.4f} ({cand_m.numerator}/{cand_m.denominator})"
            )
            print(f"PAIM13_DELTA_{label}={delta:+.4f}")
        print(f"PAIM13_REF_DECISION_P50_SECONDS={ref_p50:.4f}")
        print(f"PAIM13_PYD_DECISION_P50_SECONDS={cand_p50:.4f}")
        print(f"PAIM13_REF_DECISION_P95_SECONDS={ref_p95:.4f}")
        print(f"PAIM13_PYD_DECISION_P95_SECONDS={cand_p95:.4f}")
        if ref_p50 > 0:
            print(f"PAIM13_DECISION_P50_RATIO={cand_p50 / ref_p50:.4f}")
        if ref_p95 > 0:
            print(f"PAIM13_DECISION_P95_RATIO={cand_p95 / ref_p95:.4f}")
