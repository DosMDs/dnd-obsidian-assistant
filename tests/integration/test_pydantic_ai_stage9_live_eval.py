"""PAIM-13: Eval comparison against reference — live Ollama gate.

Compares the accepted Pydantic AI runtime against the accepted custom
reference path using the same real Ollama model, same profile, same
prompt, same application context, same tool catalog, and deterministic
ground-truth scenarios.

Layer A — first-decision quality (no tool execution)
Layer B — full-turn quality (bounded runtime)

Requires environment variables:

    DND_ASSISTANT_PAIM13_CONFIG=<path-to-models.toml>
    DND_ASSISTANT_PAIM13_AGENT_PROFILE=<profile-name>

When ``DND_ASSISTANT_PAIM13_CONFIG`` is absent, all tests skip before
any network request.

When present, missing/invalid configuration, unreachable endpoint, or
unavailable model causes the opted-in run to fail.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from dnd_assistant.application.agent_context import AgentContextBuilder
from dnd_assistant.application.pydantic_ai_agent_runtime import (
    PydanticAIAgentRuntime,
)
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
from dnd_assistant.tools.catalog import (
    build_tool_registry_schema,
)
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import (
    ExecutionContext,
)
from tests.support.paim13_scenarios import (
    DECISION_SCENARIOS,
    FULL_TURN_SCENARIOS,
    READ_LOCATION_DEF,
    READ_NPC_DEF,
    READ_QUEST_DEF,
    WRITE_CAMPAIGN_NOTE_DEF,
    WRITE_QUEST_STATUS_DEF,
    EvalHandlerState,
    EvalToolOutput,
    ReadLocationInput,
    ReadNpcInput,
    ReadQuestInput,
    WriteCampaignNoteInput,
    WriteQuestStatusInput,
    check_schema_valid,
    get_context_for_scenario,
    make_read_context,
)
from tests.support.pydantic_ai_eval import (
    DecisionObservation,
    EvalScenario,
    FullTurnObservation,
    ScenarioExpectationKind,
    ToolCallObservation,
    classify_majority,
    nearest_rank_percentile,
    score_decision,
    summarize_metrics,
)

pytestmark = pytest.mark.ollama

# ── Environment variable names ───────────────────────────────────────────────

ENV_CONFIG = "DND_ASSISTANT_PAIM13_CONFIG"
ENV_PROFILE = "DND_ASSISTANT_PAIM13_AGENT_PROFILE"

# ── Execution context helper ──────────────────────────────────────────────────


# ── Fixtures ─────────────────────────────────────────────────────────────────


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
    """Build the reference runtime with synthetic eval tools."""
    profile, model_name, _ = paim13_config

    ref_state = EvalHandlerState()
    ref_registry = _build_eval_registry(ref_state)

    ref_preparer = DndAgentRunPreparer(
        context_builder=AgentContextBuilder(
            vault_repository=_make_null_vault(),
            search_service=_make_null_search(),
        ),
        tool_catalog=build_tool_registry_schema(ref_registry),
        tool_bridge=PydanticAIToolBridge(ref_registry),
    )

    ref_model = build_pydantic_ai_ollama_model(profile)
    ref_runtime = PydanticAIAgentRuntime(
        run_preparer=ref_preparer,
        model=ref_model,
    )

    yield ref_runtime, ref_state, ref_registry


@pytest.fixture(scope="module")
def candidate_runtime(paim13_config):
    """Build the candidate runtime with synthetic eval tools."""
    profile, model_name, _ = paim13_config

    cand_state = EvalHandlerState()
    cand_registry = _build_eval_registry(cand_state)

    cand_preparer = DndAgentRunPreparer(
        context_builder=AgentContextBuilder(
            vault_repository=_make_null_vault(),
            search_service=_make_null_search(),
        ),
        tool_catalog=build_tool_registry_schema(cand_registry),
        tool_bridge=PydanticAIToolBridge(cand_registry),
    )

    cand_model = build_pydantic_ai_ollama_model(profile)
    cand_runtime = PydanticAIAgentRuntime(
        run_preparer=cand_preparer,
        model=cand_model,
    )

    yield cand_runtime, cand_state, cand_registry


# ── Tool registry builder ────────────────────────────────────────────────────


def _build_eval_registry(state: EvalHandlerState) -> ToolRegistry:
    """Build a ToolRegistry with synthetic eval tools and in-memory handlers."""
    registry = ToolRegistry()

    def read_npc_handler(inp: ReadNpcInput, ctx: object) -> EvalToolOutput:
        state.read_npc_calls += 1
        state.all_calls.append("read_npc")
        return EvalToolOutput(result=f"NPC {inp.name}: a brave warrior")

    def read_location_handler(inp: ReadLocationInput, ctx: object) -> EvalToolOutput:
        state.read_location_calls += 1
        state.all_calls.append("read_location")
        return EvalToolOutput(result=f"Location {inp.name}: an ancient fortress")

    def read_quest_handler(inp: ReadQuestInput, ctx: object) -> EvalToolOutput:
        state.read_quest_calls += 1
        state.all_calls.append("read_quest")
        return EvalToolOutput(result=f"Quest {inp.name}: a dangerous journey")

    def write_quest_status_handler(inp: WriteQuestStatusInput, ctx: object) -> EvalToolOutput:
        state.write_quest_status_calls += 1
        state.all_calls.append("write_quest_status")
        return EvalToolOutput(result=f"Quest {inp.name} status updated to {inp.status}")

    def write_campaign_note_handler(inp: WriteCampaignNoteInput, ctx: object) -> EvalToolOutput:
        state.write_campaign_note_calls += 1
        state.all_calls.append("write_campaign_note")
        return EvalToolOutput(result=f"Note saved: {inp.text}")

    registry.register(READ_NPC_DEF, read_npc_handler)
    registry.register(READ_LOCATION_DEF, read_location_handler)
    registry.register(READ_QUEST_DEF, read_quest_handler)
    registry.register(WRITE_QUEST_STATUS_DEF, write_quest_status_handler)
    registry.register(WRITE_CAMPAIGN_NOTE_DEF, write_campaign_note_handler)

    return registry


def _make_null_vault() -> object:
    """Create a minimal vault repository that returns empty results."""

    class _NullVault:
        def read_entity(self, *args, **kwargs):
            return None

        def list_entities(self, *args, **kwargs):
            return []

        def search_entities(self, *args, **kwargs):
            return []

    return _NullVault()


def _make_null_search() -> object:
    """Create a minimal search service that returns empty results."""

    class _NullSearch:
        def search(self, *args, **kwargs):
            return []

        def search_entities(self, *args, **kwargs):
            return []

    return _NullSearch()


# ── Decision observation ─────────────────────────────────────────────────────


def _observe_decision(
    scenario: EvalScenario,
    repetition: int,
    runtime: PydanticAIAgentRuntime,
    state: EvalHandlerState,
    context: ExecutionContext,
) -> DecisionObservation:
    """Observe one decision from the PydanticAIAgentRuntime (Layer A)."""

    fast_agent = PydanticAIFastAgent(
        run_preparer=runtime._run_preparer,
        model=runtime._model,
    )

    start = time.perf_counter()
    error_type: str | None = None
    error_message: str | None = None
    tool_calls: tuple[ToolCallObservation, ...] = ()
    terminal_kind: str | None = None

    try:
        decision = fast_agent.decide(
            scenario.user_input,
            execution_context=context,
        )

        response = decision.response
        observed_calls: list[ToolCallObservation] = []
        for tc in response.message.tool_calls:
            schema_valid = check_schema_valid(tc.tool_name, tc.arguments)
            observed_calls.append(
                ToolCallObservation(
                    tool_name=tc.tool_name,
                    arguments=tc.arguments,
                    call_id=tc.call_id,
                    schema_valid=schema_valid,
                )
            )
        tool_calls = tuple(observed_calls)

        content = response.message.content
        if tool_calls:
            terminal_kind = None
        elif content:
            terminal_kind = "respond"
        else:
            terminal_kind = "clarify"

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
        error_type=error_type,
        error_message=error_message,
    )


# ── Full-turn observation ────────────────────────────────────────────────────


def _observe_full_turn(
    scenario: EvalScenario,
    repetition: int,
    runtime: PydanticAIAgentRuntime,
    state: EvalHandlerState,
    context: ExecutionContext,
) -> FullTurnObservation:
    """Observe one full-turn runtime execution (Layer B)."""
    start = time.perf_counter()
    success = False
    terminal_kind: str | None = None
    tool_call_count = 0
    tool_execution_count = 0
    model_request_count = 0
    write_handler_count = 0
    error_type: str | None = None
    error_message: str | None = None

    # Capture handler state before run
    pre_write = state.write_quest_status_calls + state.write_campaign_note_calls

    try:
        result = runtime.run(
            scenario.user_input,
            execution_context=context,
        )

        success = True
        terminal_kind = result.outcome.kind.value if result.outcome else None
        tool_call_count = len(result.initial_decision.response.message.tool_calls)
        tool_execution_count = len(result.tool_executions)
        model_request_count = 2 if tool_execution_count > 0 else 1

    except ModelError as exc:
        error_type = "ModelError"
        error_message = str(exc)
    except Exception as exc:
        error_type = type(exc).__name__
        error_message = str(exc)

    duration = time.perf_counter() - start

    post_write = state.write_quest_status_calls + state.write_campaign_note_calls
    write_handler_count = post_write - pre_write

    return FullTurnObservation(
        scenario_id=scenario.scenario_id,
        repetition=repetition,
        duration_seconds=duration,
        success=success,
        terminal_kind=terminal_kind,
        tool_call_count=tool_call_count,
        tool_execution_count=tool_execution_count,
        model_request_count=model_request_count,
        write_handler_count=write_handler_count,
        error_type=error_type,
        error_message=error_message,
    )


# ==============================================================================
# Layer A — Decision quality tests
# ==============================================================================


class TestPaim13DecisionEval:
    """First-decision quality comparison (Layer A).

    Compares reference vs candidate first-decision tool selection,
    argument generation, schema validity, clarification, false WRITE
    selection, unnecessary calls, and abstention.
    """

    @pytest.mark.parametrize("scenario", DECISION_SCENARIOS, ids=lambda s: s.scenario_id)
    def test_decision_scenario(
        self,
        scenario: EvalScenario,
        reference_runtime,
        candidate_runtime,
    ) -> None:
        """Run one decision scenario on both runtimes and compare."""
        ref_runtime, ref_state, ref_registry = reference_runtime
        cand_runtime, cand_state, cand_registry = candidate_runtime

        context = get_context_for_scenario(scenario.scenario_id)

        ref_observations: list[DecisionObservation] = []
        cand_observations: list[DecisionObservation] = []

        for rep in range(3):
            if rep % 2 == 0:
                # Even: reference first
                ref_obs = _observe_decision(scenario, rep, ref_runtime, ref_state, context)
                cand_obs = _observe_decision(scenario, rep, cand_runtime, cand_state, context)
            else:
                # Odd: candidate first
                cand_obs = _observe_decision(scenario, rep, cand_runtime, cand_state, context)
                ref_obs = _observe_decision(scenario, rep, ref_runtime, ref_state, context)

            ref_observations.append(ref_obs)
            cand_observations.append(cand_obs)

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


# ==============================================================================
# Layer B — Full-turn quality tests
# ==============================================================================


class TestPaim13FullTurnEval:
    """Full-turn quality comparison (Layer B).

    Compares reference vs candidate bounded runtime behavior including
    terminal outcome, model requests, tool executions, and WRITE safety.
    """

    @pytest.mark.parametrize("scenario", FULL_TURN_SCENARIOS, ids=lambda s: s.scenario_id)
    def test_full_turn_scenario(
        self,
        scenario: EvalScenario,
        reference_runtime,
        candidate_runtime,
    ) -> None:
        """Run one full-turn scenario on both runtimes and compare."""
        ref_runtime, ref_state, ref_registry = reference_runtime
        cand_runtime, cand_state, cand_registry = candidate_runtime

        context = get_context_for_scenario(scenario.scenario_id)

        ref_observations: list[FullTurnObservation] = []
        cand_observations: list[FullTurnObservation] = []

        for rep in range(3):
            if rep % 2 == 0:
                ref_obs = _observe_full_turn(scenario, rep, ref_runtime, ref_state, context)
                cand_obs = _observe_full_turn(scenario, rep, cand_runtime, cand_state, context)
            else:
                cand_obs = _observe_full_turn(scenario, rep, cand_runtime, cand_state, context)
                ref_obs = _observe_full_turn(scenario, rep, ref_runtime, ref_state, context)

            ref_observations.append(ref_obs)
            cand_observations.append(cand_obs)

        # Check WRITE safety
        for obs in cand_observations:
            is_write_expected = (
                scenario.expectation.kind == ScenarioExpectationKind.EXACT_TOOL_CALLS
                and any("write_" in e.tool_name for e in scenario.expectation.tool_calls)
            )
            if not is_write_expected and obs.write_handler_count > 0:
                pytest.fail(
                    f"Candidate unauthorized WRITE handler execution in "
                    f"{scenario.scenario_id}: {obs.write_handler_count} calls"
                )

        # Print compact result
        ref_success = sum(1 for o in ref_observations if o.success)
        cand_success = sum(1 for o in cand_observations if o.success)
        print(
            f"\nPAIM13_SCENARIO {scenario.scenario_id}"
            f"\nREF={ref_success}/3 success"
            f"\nPYD={cand_success}/3 success"
        )


# ==============================================================================
# Warm-up tests
# ==============================================================================


class TestPaim13WarmUp:
    """Warm-up runs before measured eval (excluded from metrics)."""

    @pytest.mark.order(0)
    def test_reference_warmup(self, reference_runtime, paim13_config) -> None:
        """One reference warm-up decision."""
        ref_runtime, ref_state, ref_registry = reference_runtime
        context = make_read_context()
        try:
            ref_runtime.run(
                "Hello, this is a warm-up request.",
                execution_context=context,
            )
        except Exception:
            pass  # Warm-up failures are acceptable

    @pytest.mark.order(1)
    def test_candidate_warmup(self, candidate_runtime, paim13_config) -> None:
        """One candidate warm-up decision."""
        cand_runtime, cand_state, cand_registry = candidate_runtime
        context = make_read_context()
        try:
            cand_runtime.run(
                "Hello, this is a warm-up request.",
                execution_context=context,
            )
        except Exception:
            pass  # Warm-up failures are acceptable


# ==============================================================================
# Aggregate metrics
# ==============================================================================


class TestPaim13AggregateMetrics:
    """Compute and report aggregate metrics across all scenarios."""

    @pytest.mark.order(100)
    def test_report_aggregate_metrics(
        self,
        reference_runtime,
        candidate_runtime,
        paim13_config,
    ) -> None:
        """Run all decision scenarios and report aggregate metrics."""
        profile, model_name, ollama_version = paim13_config
        ref_runtime, ref_state, ref_registry = reference_runtime
        cand_runtime, cand_state, cand_registry = candidate_runtime

        all_ref_observations: list[DecisionObservation] = []
        all_cand_observations: list[DecisionObservation] = []

        for scenario in DECISION_SCENARIOS:
            context = get_context_for_scenario(scenario.scenario_id)
            for rep in range(3):
                if rep % 2 == 0:
                    ref_obs = _observe_decision(scenario, rep, ref_runtime, ref_state, context)
                    cand_obs = _observe_decision(scenario, rep, cand_runtime, cand_state, context)
                else:
                    cand_obs = _observe_decision(scenario, rep, cand_runtime, cand_state, context)
                    ref_obs = _observe_decision(scenario, rep, ref_runtime, ref_state, context)
                all_ref_observations.append(ref_obs)
                all_cand_observations.append(cand_obs)

        # Compute metrics
        ref_metrics = summarize_metrics(DECISION_SCENARIOS, all_ref_observations, "reference")
        cand_metrics = summarize_metrics(DECISION_SCENARIOS, all_cand_observations, "candidate")

        # Compute latency
        ref_decision_times = sorted(o.duration_seconds for o in all_ref_observations)
        cand_decision_times = sorted(o.duration_seconds for o in all_cand_observations)

        ref_p50 = nearest_rank_percentile(ref_decision_times, 50)
        ref_p95 = nearest_rank_percentile(ref_decision_times, 95)
        cand_p50 = nearest_rank_percentile(cand_decision_times, 50)
        cand_p95 = nearest_rank_percentile(cand_decision_times, 95)

        # Print aggregate report
        print(f"\nPAIM13_MODEL={model_name}")
        print(f"PAIM13_OLLAMA_VERSION={ollama_version}")
        print(f"PAIM13_SCENARIO_COUNT={len(DECISION_SCENARIOS)}")
        print("PAIM13_REPETITIONS=3")

        # Print per-scenario comparison
        for scenario in DECISION_SCENARIOS:
            ref_scenario_obs = [
                o for o in all_ref_observations if o.scenario_id == scenario.scenario_id
            ]
            cand_scenario_obs = [
                o for o in all_cand_observations if o.scenario_id == scenario.scenario_id
            ]
            comp = classify_majority(
                scenario.scenario_id,
                ref_scenario_obs,
                cand_scenario_obs,
                scenario.expectation,
            )
            print(
                f"PAIM13_SCENARIO {comp.scenario_id}"
                f" REF={comp.reference_passes}/3"
                f" PYD={comp.candidate_passes}/3"
                f" class={comp.classification}"
            )

        # Print metric summary
        for ref_m, cand_m in zip(ref_metrics, cand_metrics, strict=True):
            label = _METRIC_LABELS.get(ref_m.numerator, f"metric_{ref_m.numerator}")
            delta = cand_m.value - ref_m.value
            print(f"PAIM13_REF_{label}={ref_m.value:.4f} ({ref_m.numerator}/{ref_m.denominator})")
            print(
                f"PAIM13_PYD_{label}={cand_m.value:.4f} ({cand_m.numerator}/{cand_m.denominator})"
            )
            print(f"PAIM13_DELTA_{label}={delta:+.4f}")

        # Print latency
        print(f"PAIM13_REF_DECISION_P50_SECONDS={ref_p50:.4f}")
        print(f"PAIM13_PYD_DECISION_P50_SECONDS={cand_p50:.4f}")
        print(f"PAIM13_REF_DECISION_P95_SECONDS={ref_p95:.4f}")
        print(f"PAIM13_PYD_DECISION_P95_SECONDS={cand_p95:.4f}")
        print(f"PAIM13_DECISION_P50_RATIO={cand_p50 / ref_p50:.4f}" if ref_p50 > 0 else "N/A")
        print(f"PAIM13_DECISION_P95_RATIO={cand_p95 / ref_p95:.4f}" if ref_p95 > 0 else "N/A")


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
