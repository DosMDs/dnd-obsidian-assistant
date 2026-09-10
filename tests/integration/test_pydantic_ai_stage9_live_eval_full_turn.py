"""PAIM-13: Eval comparison — Layer B full-turn quality + aggregate + warmup.

Compares reference (AgentLoop) vs candidate (PydanticAIAgentRuntime)
bounded runtime behavior across 9 full-turn scenarios x 3 repetitions,
plus aggregate metrics and warm-up runs.

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

from dnd_assistant.application.agent_loop import AgentLoop
from dnd_assistant.application.agent_tool_execution import (
    AgentToolExecutionService,
)
from dnd_assistant.application.fast_agent import FastAgent
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
from dnd_assistant.tools.catalog import build_tool_registry_schema
from dnd_assistant.tools.executor import ToolExecutor
from dnd_assistant.tools.types import (
    ExecutionContext,
)
from tests.support.paim13_live_harness import (
    CountingModelGateway,
    CountingPydanticModel,
    Paim13OllamaEnvironment,
    build_eval_registry,
    make_deterministic_context_builder,
    parse_terminal_observation,
    probe_ollama_environment,
)
from tests.support.paim13_scenarios import (
    FULL_TURN_SCENARIOS,
    EvalHandlerState,
    get_context_for_scenario,
    make_read_context,
)
from tests.support.pydantic_ai_eval import (
    EvalScenario,
    ExposedToolInfo,
    FullTurnObservation,
    ToolCallObservation,
    count_unauthorized_write_handler_executions,
    score_full_turn,
)
from tests.support.pydantic_ai_eval_datasets import (
    FrozenFullTurnDataset,
    summarize_full_turn_aggregate,
)

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

    env: Paim13OllamaEnvironment = probe_ollama_environment(profile)

    return profile, env.model_name, env.server_version


@pytest.fixture(scope="module")
def reference_runtime(paim13_config):
    """Build the reference full-turn runtime.

    Reference path:
        OllamaModelProvider(profile)
        -> CountingModelGateway
        -> FastAgent
        -> AgentLoop
        -> AgentToolExecutionService
        -> ToolExecutor
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

    ref_loop = AgentLoop(
        context_builder=ref_context_builder,
        model_gateway=counting_gateway,
        tool_catalog=ref_catalog,
        tool_execution_service=AgentToolExecutionService(tool_executor=ToolExecutor(ref_registry)),
    )

    yield {
        "fast_agent": ref_fast_agent,
        "loop": ref_loop,
        "state": ref_state,
        "registry": ref_registry,
        "counting_gateway": counting_gateway,
        "native_provider": native_provider,
        "profile": profile,
    }

    native_provider.close()


@pytest.fixture(scope="module")
def candidate_runtime(paim13_config):
    """Build the candidate full-turn runtime.

    Candidate path:
        build_pydantic_ai_ollama_model(profile)
        -> CountingPydanticModel wrapper
        -> PydanticAIFastAgent
        -> PydanticAIAgentRuntime
        -> DndAgentRunPreparer
        -> PydanticAIToolBridge
        -> ToolExecutor
    """
    profile, model_name, _ = paim13_config

    cand_state = EvalHandlerState()
    cand_registry = build_eval_registry(cand_state)
    cand_catalog = build_tool_registry_schema(cand_registry)
    cand_context_builder = make_deterministic_context_builder()

    cand_tool_bridge = PydanticAIToolBridge(registry=cand_registry)
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

    cand_runtime = PydanticAIAgentRuntime(
        run_preparer=cand_preparer,
        model=counting_model,
    )

    yield {
        "fast_agent": cand_fast_agent,
        "runtime": cand_runtime,
        "state": cand_state,
        "registry": cand_registry,
        "preparer": cand_preparer,
        "counting_model": counting_model,
        "profile": profile,
    }


# ── Frozen dataset fixture (warm-up + collection exactly once) ────────────────


def _warmup(fast_agent: FastAgent | PydanticAIFastAgent) -> None:
    """Perform one warm-up decision on each FastAgent (excluded from metrics).

    Uses the direct FastAgent ``decide()`` path — symmetric for both reference
    and candidate.  Validates zero tool calls and a valid terminal outcome.
    Warm-up failure must fail fixture construction — exceptions are not
    swallowed.
    """
    context = make_read_context()
    decision = fast_agent.decide(
        "Hello, this is a warm-up request.",
        execution_context=context,
    )
    tool_calls = decision.response.message.tool_calls
    if tool_calls:
        raise RuntimeError(f"Warm-up produced {len(tool_calls)} tool call(s); expected zero.")
    terminal_kind = parse_terminal_observation(decision.response, tool_calls)
    if terminal_kind is None:
        raise RuntimeError("Warm-up produced no valid terminal outcome.")


@pytest.fixture(scope="module")
def frozen_full_turn_dataset(
    reference_runtime,
    candidate_runtime,
) -> FrozenFullTurnDataset:
    """Collect all Layer B observations exactly once with warm-up first.

    Warm-up runs before any measured observation.  The returned dataset
    is consumed by scenario tests and aggregate metrics — no additional
    model calls.
    """
    ref_runtime = reference_runtime
    cand_runtime = candidate_runtime

    # Warm-up before measurement (excluded from all metrics)
    # Uses direct FastAgent decide() — symmetric for both sides.
    _warmup(ref_runtime["fast_agent"])
    _warmup(cand_runtime["fast_agent"])

    ref_observations: list[FullTurnObservation] = []
    cand_observations: list[FullTurnObservation] = []

    for scenario in FULL_TURN_SCENARIOS:
        context = get_context_for_scenario(scenario.scenario_id)
        for rep in range(3):
            if rep % 2 == 0:
                ref_obs = _observe_reference_full_turn(scenario, rep, ref_runtime, context)
                cand_obs = _observe_candidate_full_turn(scenario, rep, cand_runtime, context)
            else:
                cand_obs = _observe_candidate_full_turn(scenario, rep, cand_runtime, context)
                ref_obs = _observe_reference_full_turn(scenario, rep, ref_runtime, context)
            ref_observations.append(ref_obs)
            cand_observations.append(cand_obs)

    return FrozenFullTurnDataset(
        scenarios=tuple(FULL_TURN_SCENARIOS),
        reference_observations=tuple(ref_observations),
        candidate_observations=tuple(cand_observations),
    )


# ── Layer B: Reference full-turn observer ─────────────────────────────────────


def _observe_reference_full_turn(
    scenario: EvalScenario,
    repetition: int,
    runtime: dict[str, Any],
    context: ExecutionContext,
) -> FullTurnObservation:
    """Observe one full-turn from the reference AgentLoop (Layer B)."""
    loop: AgentLoop = runtime["loop"]
    state: EvalHandlerState = runtime["state"]
    counting_gateway: CountingModelGateway = runtime["counting_gateway"]

    start = time.perf_counter()
    success = False
    terminal_kind: str | None = None
    initial_calls: tuple[ToolCallObservation, ...] = ()
    executed_calls: tuple[ToolCallObservation, ...] = ()
    tool_call_count = 0
    tool_execution_count = 0
    write_handler_count = 0
    error_type: str | None = None
    error_message: str | None = None
    exposed_info: ExposedToolInfo | None = None

    # Capture handler state before run
    pre_all = len(state.all_calls)
    pre_write = state.write_quest_status_calls + state.write_campaign_note_calls

    # Capture counting gateway state before run
    pre_count = counting_gateway.state.chat_with_tools_count

    try:
        result = loop.run(
            scenario.user_input,
            execution_context=context,
        )

        success = True
        terminal_kind = result.outcome.kind.value if result.outcome else None

        # Initial tool calls from first decision
        initial_tcs = result.initial_decision.response.message.tool_calls
        tool_call_count = len(initial_tcs)
        initial_calls = tuple(
            ToolCallObservation(
                tool_name=tc.name,
                arguments=dict(tc.arguments),
                call_id=tc.call_id,
                schema_valid=True,
            )
            for tc in initial_tcs
        )

        # Executed tool calls
        tool_execution_count = len(result.tool_executions)
        executed_calls = tuple(
            ToolCallObservation(
                tool_name=exec.tool_call.name,
                arguments=dict(exec.tool_call.arguments),
                call_id=exec.tool_call.call_id,
                schema_valid=True,
            )
            for exec in result.tool_executions
        )

        # Exposed tools
        exposed_names = tuple(t.name for t in result.initial_decision.exposed_tools)
        has_write = any(
            t.permission.value == "write" for t in result.initial_decision.exposed_tools
        )
        exposed_info = ExposedToolInfo(tool_names=exposed_names, has_write=has_write)

    except ModelError as exc:
        error_type = "ModelError"
        error_message = str(exc)
    except Exception as exc:
        error_type = type(exc).__name__
        error_message = str(exc)

    duration = time.perf_counter() - start

    post_all = len(state.all_calls)
    post_write = state.write_quest_status_calls + state.write_campaign_note_calls
    handler_call_count = post_all - pre_all
    write_handler_count = post_write - pre_write
    model_request_count = counting_gateway.state.chat_with_tools_count - pre_count

    return FullTurnObservation(
        scenario_id=scenario.scenario_id,
        repetition=repetition,
        duration_seconds=duration,
        success=success,
        terminal_kind=terminal_kind,
        initial_tool_calls=initial_calls,
        executed_tool_calls=executed_calls,
        tool_call_count=tool_call_count,
        tool_execution_count=tool_execution_count,
        model_request_count=model_request_count,
        handler_call_count=handler_call_count,
        write_handler_count=write_handler_count,
        exposed_tools=exposed_info,
        error_type=error_type,
        error_message=error_message,
    )


# ── Layer B: Candidate full-turn observer ─────────────────────────────────────


def _observe_candidate_full_turn(
    scenario: EvalScenario,
    repetition: int,
    runtime: dict[str, Any],
    context: ExecutionContext,
) -> FullTurnObservation:
    """Observe one full-turn from the candidate PydanticAIAgentRuntime (Layer B)."""
    cand_runtime: PydanticAIAgentRuntime = runtime["runtime"]
    state: EvalHandlerState = runtime["state"]
    counting_model: CountingPydanticModel = runtime["counting_model"]

    start = time.perf_counter()
    success = False
    terminal_kind: str | None = None
    initial_calls: tuple[ToolCallObservation, ...] = ()
    executed_calls: tuple[ToolCallObservation, ...] = ()
    tool_call_count = 0
    tool_execution_count = 0
    model_request_count = 0
    write_handler_count = 0
    error_type: str | None = None
    error_message: str | None = None
    exposed_info: ExposedToolInfo | None = None

    # Capture handler state before run
    pre_all = len(state.all_calls)
    pre_write = state.write_quest_status_calls + state.write_campaign_note_calls

    # Capture counting model state before run
    pre_count = counting_model.state.request_count

    try:
        result = cand_runtime.run(
            scenario.user_input,
            execution_context=context,
        )

        success = True
        terminal_kind = result.outcome.kind.value if result.outcome else None

        # Initial tool calls from first decision
        initial_tcs = result.initial_decision.response.message.tool_calls
        tool_call_count = len(initial_tcs)
        initial_calls = tuple(
            ToolCallObservation(
                tool_name=tc.name,
                arguments=dict(tc.arguments),
                call_id=tc.call_id,
                schema_valid=True,
            )
            for tc in initial_tcs
        )

        # Executed tool calls
        tool_execution_count = len(result.tool_executions)
        executed_calls = tuple(
            ToolCallObservation(
                tool_name=exec.tool_call.name,
                arguments=dict(exec.tool_call.arguments),
                call_id=exec.tool_call.call_id,
                schema_valid=True,
            )
            for exec in result.tool_executions
        )

        # Exposed tools
        exposed_names = tuple(t.name for t in result.initial_decision.exposed_tools)
        has_write = any(
            t.permission.value == "write" for t in result.initial_decision.exposed_tools
        )
        exposed_info = ExposedToolInfo(tool_names=exposed_names, has_write=has_write)

    except ModelError as exc:
        error_type = "ModelError"
        error_message = str(exc)
    except Exception as exc:
        error_type = type(exc).__name__
        error_message = str(exc)

    # Literal model request count from CountingPydanticModel delta
    # Computed on ALL paths (successful, errored, failed) — never inferred.
    model_request_count = counting_model.state.request_count - pre_count

    # Hard check: candidate must not perform a third semantic request.
    # This is a critical PAIM-13 failure that cannot be silently swallowed.
    if model_request_count > 2:
        success = False
        error_type = "RequestLimitViolation"
        error_message = (
            f"Candidate performed {model_request_count} semantic requests "
            f"(max 2 allowed). This is a critical PAIM-13 failure."
        )

    duration = time.perf_counter() - start

    post_all = len(state.all_calls)
    post_write = state.write_quest_status_calls + state.write_campaign_note_calls
    handler_call_count = post_all - pre_all
    write_handler_count = post_write - pre_write

    return FullTurnObservation(
        scenario_id=scenario.scenario_id,
        repetition=repetition,
        duration_seconds=duration,
        success=success,
        terminal_kind=terminal_kind,
        initial_tool_calls=initial_calls,
        executed_tool_calls=executed_calls,
        tool_call_count=tool_call_count,
        tool_execution_count=tool_execution_count,
        model_request_count=model_request_count,
        handler_call_count=handler_call_count,
        write_handler_count=write_handler_count,
        exposed_tools=exposed_info,
        error_type=error_type,
        error_message=error_message,
    )


# ==============================================================================
# Layer B — Full-turn quality tests
# ==============================================================================


class TestPaim13FullTurnEval:
    """Full-turn quality comparison (Layer B).

    All observations come from the frozen dataset — no additional model calls.
    """

    @pytest.mark.parametrize("scenario", FULL_TURN_SCENARIOS, ids=lambda s: s.scenario_id)
    def test_full_turn_scenario(
        self,
        scenario: EvalScenario,
        frozen_full_turn_dataset: FrozenFullTurnDataset,
    ) -> None:
        """Score one full-turn scenario from the frozen dataset."""
        ref_observations = [
            o
            for o in frozen_full_turn_dataset.reference_observations
            if o.scenario_id == scenario.scenario_id
        ]
        cand_observations = [
            o
            for o in frozen_full_turn_dataset.candidate_observations
            if o.scenario_id == scenario.scenario_id
        ]

        for obs in cand_observations:
            unauthorized = count_unauthorized_write_handler_executions(obs, scenario.expectation)
            if unauthorized > 0:
                pytest.fail(
                    f"Candidate unauthorized WRITE in {scenario.scenario_id}: "
                    f"{unauthorized} unauthorized handler execution(s) "
                    f"(write_handler_count={obs.write_handler_count})"
                )
        ref_passes = sum(1 for o in ref_observations if score_full_turn(o, scenario.expectation))
        cand_passes = sum(1 for o in cand_observations if score_full_turn(o, scenario.expectation))
        print(
            f"\nPAIM13_SCENARIO {scenario.scenario_id}\nREF={ref_passes}/3 pass\nPYD={cand_passes}/3 pass"
        )


# ==============================================================================
# Full-turn aggregate summary
# ==============================================================================


class TestPaim13FullTurnAggregate:
    """Aggregate summary over the frozen Layer B dataset.

    All values derived from the frozen observations — no additional model calls.
    """

    def test_report_full_turn_aggregate(
        self,
        frozen_full_turn_dataset: FrozenFullTurnDataset,
        paim13_config,
    ) -> None:
        profile, model_name, ollama_version = paim13_config
        ref_observations = list(frozen_full_turn_dataset.reference_observations)
        cand_observations = list(frozen_full_turn_dataset.candidate_observations)

        ref_summary = summarize_full_turn_aggregate(
            list(FULL_TURN_SCENARIOS), ref_observations, "reference"
        )
        cand_summary = summarize_full_turn_aggregate(
            list(FULL_TURN_SCENARIOS), cand_observations, "candidate"
        )

        # ── Compute all blocker conditions before failing ─────────────────
        blockers: list[str] = []

        # 1. Unauthorized WRITE handler executions
        if cand_summary.unauthorized_write_handler_count > 0:
            blockers.append(
                f"unauthorized WRITE handler executions: "
                f"{cand_summary.unauthorized_write_handler_count}"
            )

        # 2. Turns with excess requests
        if cand_summary.turns_with_excess_requests > 0:
            blockers.append(f"turns with >2 requests: {cand_summary.turns_with_excess_requests}")

        # 3. Critical scenario REFERENCE_ONLY_PASS
        cand_obs_by_scenario: dict[str, list[FullTurnObservation]] = {}
        for obs in cand_observations:
            cand_obs_by_scenario.setdefault(obs.scenario_id, []).append(obs)
        ref_obs_by_scenario: dict[str, list[FullTurnObservation]] = {}
        for obs in ref_observations:
            ref_obs_by_scenario.setdefault(obs.scenario_id, []).append(obs)

        critical_ref_only: list[str] = []
        for scenario in FULL_TURN_SCENARIOS:
            if not scenario.critical_regression:
                continue
            ref_s_obs = ref_obs_by_scenario.get(scenario.scenario_id, [])
            cand_s_obs = cand_obs_by_scenario.get(scenario.scenario_id, [])
            ref_passes = sum(1 for o in ref_s_obs if score_full_turn(o, scenario.expectation))
            cand_passes = sum(1 for o in cand_s_obs if score_full_turn(o, scenario.expectation))
            ref_majority = ref_passes >= 2
            cand_majority = cand_passes >= 2
            if ref_majority and not cand_majority:
                critical_ref_only.append(
                    f"{scenario.scenario_id}: REFERENCE_ONLY_PASS "
                    f"(reference {ref_passes}/3, candidate {cand_passes}/3)"
                )
        if critical_ref_only:
            blockers.append(f"critical REFERENCE_ONLY_PASS: {'; '.join(critical_ref_only)}")

        # ── Emit all blockers together before failing ────────────────
        if blockers:
            print(f"\nPAIM13_HARD_BLOCKERS ({len(blockers)}):")
            for b in blockers:
                print(f"  - {b}")

        print(f"\nPAIM13_MODEL={model_name}")
        print(f"PAIM13_OLLAMA_VERSION={ollama_version}")
        print(f"PAIM13_FULL_TURN_SCENARIO_COUNT={len(FULL_TURN_SCENARIOS)}")
        print("PAIM13_FULL_TURN_REPETITIONS=3")

        for label, ref_val, cand_val in [
            (
                "SCENARIO_MAJORITY_SUCCESS",
                ref_summary.scenario_majority_success,
                cand_summary.scenario_majority_success,
            ),
            (
                "TOTAL_MODEL_REQUESTS",
                ref_summary.total_model_requests,
                cand_summary.total_model_requests,
            ),
            (
                "MEAN_MODEL_REQUESTS",
                ref_summary.mean_model_requests,
                cand_summary.mean_model_requests,
            ),
            (
                "TOTAL_INITIAL_TOOL_CALLS",
                ref_summary.total_initial_tool_calls,
                cand_summary.total_initial_tool_calls,
            ),
            (
                "MEAN_INITIAL_TOOL_CALLS",
                ref_summary.mean_initial_tool_calls,
                cand_summary.mean_initial_tool_calls,
            ),
            (
                "TOTAL_EXECUTED_TOOL_CALLS",
                ref_summary.total_executed_tool_calls,
                cand_summary.total_executed_tool_calls,
            ),
            (
                "MEAN_EXECUTED_TOOL_CALLS",
                ref_summary.mean_executed_tool_calls,
                cand_summary.mean_executed_tool_calls,
            ),
            (
                "TOTAL_HANDLER_INVOCATIONS",
                ref_summary.total_handler_invocations,
                cand_summary.total_handler_invocations,
            ),
            (
                "MEAN_HANDLER_INVOCATIONS",
                ref_summary.mean_handler_invocations,
                cand_summary.mean_handler_invocations,
            ),
            (
                "UNAUTHORIZED_WRITE_HANDLER_COUNT",
                ref_summary.unauthorized_write_handler_count,
                cand_summary.unauthorized_write_handler_count,
            ),
            (
                "TURNS_WITH_EXCESS_REQUESTS",
                ref_summary.turns_with_excess_requests,
                cand_summary.turns_with_excess_requests,
            ),
        ]:
            print(f"PAIM13_REF_{label}={ref_val}")
            print(f"PAIM13_PYD_{label}={cand_val}")
            if isinstance(ref_val, (int, float)) and isinstance(cand_val, (int, float)):
                print(f"PAIM13_DELTA_{label}={cand_val - ref_val:+.4f}")

        print(f"PAIM13_REF_FULL_TURN_P50_SECONDS={ref_summary.p50_seconds:.4f}")
        print(f"PAIM13_PYD_FULL_TURN_P50_SECONDS={cand_summary.p50_seconds:.4f}")
        print(f"PAIM13_REF_FULL_TURN_P95_SECONDS={ref_summary.p95_seconds:.4f}")
        print(f"PAIM13_PYD_FULL_TURN_P95_SECONDS={cand_summary.p95_seconds:.4f}")
        if ref_summary.p50_seconds > 0:
            print(
                f"PAIM13_FULL_TURN_P50_RATIO={cand_summary.p50_seconds / ref_summary.p50_seconds:.4f}"
            )
        if ref_summary.p95_seconds > 0:
            print(
                f"PAIM13_FULL_TURN_P95_RATIO={cand_summary.p95_seconds / ref_summary.p95_seconds:.4f}"
            )

        # ── Consolidated blocker failure (after all metrics emitted) ──
        if blockers:
            pytest.fail(
                f"PAIM-13 hard blockers ({len(blockers)}):\n"
                + "\n".join(f"  - {b}" for b in blockers)
            )


# ==============================================================================
# Warm-up is handled by the frozen_full_turn_dataset fixture
# (before any measured observation collection).
# ==============================================================================
