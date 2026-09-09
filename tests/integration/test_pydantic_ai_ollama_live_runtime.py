"""PAIM-12: Real Ollama smoke/performance gate for Pydantic AI runtime.

Opt-in tests requiring a running local Ollama instance and explicit
environment configuration.

Environment variables:

    DND_ASSISTANT_PAIM12_CONFIG=<path-to-models.toml>
    DND_ASSISTANT_PAIM12_AGENT_PROFILE=<profile-name>

When ``DND_ASSISTANT_PAIM12_CONFIG`` is absent, all tests skip before
any network request.

When present, missing/invalid configuration, unreachable endpoint, or
unavailable model causes the opted-in run to fail.

Scenarios
---------

P12-L01  Live profile + native health + /api/version + /api/tags preflight
P12-L02  Real production Pydantic model factory identity/settings evidence
P12-L03  3x direct production-runtime terminal smoke + latency samples
P12-L04  3x real single-READ production-runtime tool round-trip + latency
"""

from __future__ import annotations

import os
import statistics
import time
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from dnd_assistant.application.agent_context import AgentContextBuilder
from dnd_assistant.application.agent_loop import AgentOutcomeKind
from dnd_assistant.application.pydantic_ai_agent_runtime import (
    PydanticAIAgentRuntime,
)
from dnd_assistant.application.pydantic_ai_run_deps import (
    DndAgentRunPreparer,
)
from dnd_assistant.application.pydantic_ai_tool_bridge import (
    PydanticAIToolBridge,
)
from dnd_assistant.errors import NotFoundError
from dnd_assistant.models.ollama import OllamaModelProvider
from dnd_assistant.models.pydantic_ai_ollama import (
    build_pydantic_ai_ollama_model,
)
from dnd_assistant.retrieval.service import SearchService
from dnd_assistant.retrieval.types import SearchHit, SearchQuery
from dnd_assistant.storage.session_events import RawSessionEvent
from dnd_assistant.storage.session_metadata import RawSessionMetadata
from dnd_assistant.storage.types import VaultDocument, VaultRepository
from dnd_assistant.tools.catalog import (
    build_tool_registry_schema,
)
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import (
    Permission,
    SessionMode,
)
from dnd_assistant.tools.types import (
    ToolDefinition as ProjectToolDefinition,
)
from tests.support.pydantic_ai_runtime import (
    make_read_context,
)

pytestmark = pytest.mark.ollama

# ── Environment variable names ───────────────────────────────────────────────

ENV_CONFIG = "DND_ASSISTANT_PAIM12_CONFIG"
ENV_PROFILE = "DND_ASSISTANT_PAIM12_AGENT_PROFILE"

# ── Probe tool schema ────────────────────────────────────────────────────────


class Paim12ProbeInput(BaseModel):
    token: str


class Paim12ProbeOutput(BaseModel):
    result: str


# ── Probe handler counter ────────────────────────────────────────────────────


@dataclass
class Paim12ProbeState:
    """Mutable counter owned by the tool-runtime fixture.

    Fresh instance per module scope — tracks handler invocations
    across all tool samples within one module run.
    """

    calls: int = 0


# ── Fixtures ─────────────────────────────────────────────────────────────────


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        pytest.fail(
            f"Explicit PAIM-12 opt-in detected ({ENV_CONFIG} is set), "
            f"but required variable {name} is missing or empty."
        )
    return value


@pytest.fixture(scope="module")
def paim12_config_path() -> Path:
    """Load and validate the PAIM-12 config path from environment.

    When ``DND_ASSISTANT_PAIM12_CONFIG`` is absent, skip all tests
    before any network request.
    """
    raw = os.environ.get(ENV_CONFIG)
    if not raw:
        pytest.skip(f"{ENV_CONFIG} is not set -- skipping PAIM-12 live tests")
    path = Path(raw)
    if not path.exists():
        pytest.fail(
            f"Explicit PAIM-12 opt-in detected ({ENV_CONFIG}={raw}), "
            f"but config file not found: {path}"
        )
    return path


@pytest.fixture(scope="module")
def paim12_profile_name() -> str:
    return _require_env(ENV_PROFILE)


@pytest.fixture(scope="module")
def paim12_config(paim12_config_path: Path) -> Any:
    """Load model profiles config from the PAIM-12 config path."""
    from dnd_assistant.models.profiles import load_model_profiles

    try:
        return load_model_profiles(paim12_config_path)
    except Exception as exc:
        pytest.fail(f"Failed to load PAIM-12 config from {paim12_config_path}: {exc}")


@pytest.fixture(scope="module")
def paim12_profile(paim12_config: Any, paim12_profile_name: str) -> Any:
    """Get the selected agent profile from the config."""
    if paim12_profile_name not in paim12_config.profiles:
        pytest.fail(
            f"PAIM-12 profile {paim12_profile_name!r} not found in config. "
            f"Available: {list(paim12_config.profiles)}"
        )
    profile = paim12_config.profiles[paim12_profile_name]
    if profile.provider != "ollama":
        pytest.fail(
            f"PAIM-12 profile {paim12_profile_name!r} has "
            f"provider={profile.provider!r}, expected 'ollama'"
        )
    return profile


# ── Shared runtime builder ───────────────────────────────────────────────────


def _build_paim12_runtime(
    paim12_profile: Any,
    registry: ToolRegistry,
) -> PydanticAIAgentRuntime:
    """Build a PydanticAIAgentRuntime from profile and pre-configured registry.

    All stubs are identical across direct and tool variants — only the
    registry contents differ.
    """

    class _StubSearchService(SearchService):
        def search(self, query: SearchQuery, *, limit: int = 5) -> Sequence[SearchHit]:
            return []

    class _StubVaultRepository(VaultRepository):
        def get_entity(self, entity_id: str) -> VaultDocument:
            raise ValueError("unexpected call")

    class _StubSessionRepo:
        def get_active_session(self) -> RawSessionMetadata | None:
            return None

    class _StubEventRepo:
        def list_events(self, session_id: str) -> list[RawSessionEvent]:
            return []

    class _StubWorldTimeRepo:
        def get_current_world_time(self) -> None:
            raise NotFoundError("no world time")

    catalog = build_tool_registry_schema(registry)
    bridge = PydanticAIToolBridge(registry=registry)
    context_builder = AgentContextBuilder(
        search_service=_StubSearchService(),
        vault_repository=_StubVaultRepository(),
        session_repository=_StubSessionRepo(),
        event_repository=_StubEventRepo(),
        world_time_repository=_StubWorldTimeRepo(),
    )
    preparer = DndAgentRunPreparer(
        context_builder=context_builder,
        tool_catalog=catalog,
        tool_bridge=bridge,
    )
    model = build_pydantic_ai_ollama_model(paim12_profile)
    return PydanticAIAgentRuntime(
        run_preparer=preparer,
        model=model,
    )


@pytest.fixture(scope="module")
def paim12_direct_runtime(paim12_profile: Any) -> PydanticAIAgentRuntime:
    """Runtime with ZERO tools — pure RESPOND-only smoke."""
    registry = ToolRegistry()
    return _build_paim12_runtime(paim12_profile, registry)


@pytest.fixture(scope="module")
def paim12_tool_runtime(
    paim12_profile: Any,
) -> tuple[PydanticAIAgentRuntime, Paim12ProbeState]:
    """Runtime with exactly ``read_paim12_probe`` and a shared counter.

    Returns (runtime, state) so each test can assert handler deltas.
    """
    state = Paim12ProbeState()
    registry = ToolRegistry()

    def probe_handler(inp: Paim12ProbeInput, ctx: object) -> Paim12ProbeOutput:
        state.calls += 1
        return Paim12ProbeOutput(result=f"PAIM12-PROBE:{inp.token}")

    probe_def = ProjectToolDefinition(
        name="read_paim12_probe",
        description=(
            "Authoritative probe tool for PAIM-12 verification. "
            "Use this tool to obtain the requested probe value."
        ),
        input_schema=Paim12ProbeInput,
        output_schema=Paim12ProbeOutput,
        permission=Permission.READ,
        side_effects=frozenset(),
        allowed_session_modes=frozenset(
            {
                SessionMode.ACTIVE_SESSION,
                SessionMode.NO_ACTIVE_SESSION,
            }
        ),
    )
    registry.register(probe_def, probe_handler)
    runtime = _build_paim12_runtime(paim12_profile, registry)
    return runtime, state


# ═══════════════════════════════════════════════════════════════════════════════
# P12-L01: Live profile + native health + /api/version + /api/tags preflight
# ═══════════════════════════════════════════════════════════════════════════════


class TestP12L01Preflight:
    """Native health, version, and tags preflight."""

    def test_profile_boundary(self, paim12_profile: Any) -> None:
        """Verify the selected profile satisfies PAIM-12 requirements."""
        from dnd_assistant.models.profiles import ModelProfileRole

        assert paim12_profile.provider == "ollama"
        assert paim12_profile.role is ModelProfileRole.AGENT
        assert paim12_profile.keep_alive is None

    def test_native_health(self, paim12_profile: Any) -> None:
        """Native OllamaModelProvider health check."""
        provider = OllamaModelProvider(paim12_profile)
        try:
            health = provider.health()
            assert health.reachable is True, f"Ollama not reachable: {health.detail}"
            assert health.model_available is True, f"Model not available: {health.detail}"
        finally:
            provider.close()

    def test_api_version(self, paim12_profile: Any) -> None:
        """Discover exact current Ollama version from /api/version."""
        provider = OllamaModelProvider(paim12_profile)
        try:
            resp = provider._client.get(provider._url("/api/version"))
            assert resp.is_success, f"/api/version HTTP {resp.status_code}"
            data = resp.json()
            assert isinstance(data, dict)
            version = data.get("version")
            assert isinstance(version, str) and version.strip(), (
                f"Invalid version response: {data!r}"
            )
            version = version.strip()
            print(f"\nPAIM12_OLLAMA_VERSION={version}")
        finally:
            provider.close()

    def test_api_tags(self, paim12_profile: Any) -> None:
        """Verify selected model is present in /api/tags."""
        provider = OllamaModelProvider(paim12_profile)
        try:
            resp = provider._client.get(provider._url("/api/tags"))
            assert resp.is_success, f"/api/tags HTTP {resp.status_code}"
            data = resp.json()
            assert isinstance(data, dict) and "models" in data
            models_list = data["models"]
            assert isinstance(models_list, list)
            model_names = []
            for m in models_list:
                name = m.get("name", "") if isinstance(m, dict) else ""
                model_names.append(name)
            configured = paim12_profile.model
            assert configured in model_names, (
                f"Model {configured!r} not found in /api/tags. Installed: {model_names}"
            )
            print(f"\nPAIM12_MODEL={configured}")
            print(f"PAIM12_TAGS_COUNT={len(models_list)}")
        finally:
            provider.close()


# ==============================================================================
# P12-L02: Real production Pydantic model factory identity/settings
# ==============================================================================


class TestP12L02Factory:
    """Production Pydantic model factory identity and settings."""

    def test_factory_returns_ollama_model(self, paim12_profile: Any) -> None:
        """build_pydantic_ai_ollama_model returns an OllamaModel."""
        from pydantic_ai.models.ollama import OllamaModel

        model = build_pydantic_ai_ollama_model(paim12_profile)
        assert type(model) is OllamaModel

    def test_factory_settings(self, paim12_profile: Any) -> None:
        """Verify model_name, system, and model identity."""
        from pydantic_ai.models.ollama import OllamaModel

        model = build_pydantic_ai_ollama_model(paim12_profile)
        assert isinstance(model, OllamaModel)
        assert model.system == "ollama"
        assert model.model_name == paim12_profile.model


# ==============================================================================
# P12-L03: 3x direct production-runtime terminal smoke + latency
# ==============================================================================


class TestP12L03DirectSmoke:
    """Direct terminal smoke — zero tools, pure RESPOND."""

    _durations: list[float] = []

    def _run_direct(self, runtime: PydanticAIAgentRuntime, marker: str) -> Any:
        """Run a direct terminal smoke and return the result."""
        context = make_read_context()
        user_input = (
            f"Return a RESPOND terminal answer whose message contains "
            f"{marker}. No tools are available."
        )
        return runtime.run(
            user_input,
            execution_context=context,
        )

    def _assert_direct_result(self, result: Any, marker: str) -> None:
        """Assert direct-smoke invariants."""
        assert result.outcome.kind is AgentOutcomeKind.RESPOND
        assert marker in result.outcome.message
        assert result.tool_executions == ()

    def test_direct_sample_1(self, paim12_direct_runtime: PydanticAIAgentRuntime) -> None:
        t0 = time.perf_counter()
        result = self._run_direct(paim12_direct_runtime, "PAIM12-DIRECT-OK")
        duration = time.perf_counter() - t0
        TestP12L03DirectSmoke._durations.append(duration)
        print(f"\nPAIM12_DIRECT_1={duration:.3f}s")
        self._assert_direct_result(result, "PAIM12-DIRECT-OK")

    def test_direct_sample_2(self, paim12_direct_runtime: PydanticAIAgentRuntime) -> None:
        t0 = time.perf_counter()
        result = self._run_direct(paim12_direct_runtime, "PAIM12-DIRECT-OK")
        duration = time.perf_counter() - t0
        TestP12L03DirectSmoke._durations.append(duration)
        print(f"\nPAIM12_DIRECT_2={duration:.3f}s")
        self._assert_direct_result(result, "PAIM12-DIRECT-OK")

    def test_direct_sample_3(self, paim12_direct_runtime: PydanticAIAgentRuntime) -> None:
        t0 = time.perf_counter()
        result = self._run_direct(paim12_direct_runtime, "PAIM12-DIRECT-OK")
        duration = time.perf_counter() - t0
        TestP12L03DirectSmoke._durations.append(duration)
        print(f"\nPAIM12_DIRECT_3={duration:.3f}s")
        self._assert_direct_result(result, "PAIM12-DIRECT-OK")

    @classmethod
    def teardown_class(cls) -> None:
        vals = cls._durations
        if vals:
            print(f"\nPAIM12_DIRECT_SECONDS={vals}")
            print(f"PAIM12_DIRECT_MIN_SECONDS={min(vals):.3f}")
            print(f"PAIM12_DIRECT_MEDIAN_SECONDS={statistics.median(vals):.3f}")
            print(f"PAIM12_DIRECT_MAX_SECONDS={max(vals):.3f}")
            print("PAIM12_DIRECT_RELIABILITY=3/3")


# ==============================================================================
# P12-L04: 3x real single-READ production-runtime tool round-trip + latency
# ==============================================================================


class TestP12L04ToolSmoke:
    """Single-READ tool round-trip through real Ollama runtime."""

    _durations: list[float] = []

    def _run_tool(
        self,
        runtime: PydanticAIAgentRuntime,
        token: str,
    ) -> Any:
        """Run a single-tool round-trip and return the result."""
        context = make_read_context()
        user_input = (
            f'Use read_paim12_probe exactly once with token "{token}". '
            f"Do not guess the probe result. "
            f"After the tool returns, finish with a RESPOND terminal "
            f"answer whose message includes the exact probe marker."
        )
        return runtime.run(
            user_input,
            execution_context=context,
        )

    def _assert_tool_result(
        self,
        result: Any,
        token: str,
        *,
        before: int,
        state: Paim12ProbeState,
    ) -> None:
        """Assert tool-round-trip invariants including handler delta."""
        # Handler delta
        assert state.calls == before + 1, (
            f"Expected handler call delta +1 (before={before}, after={state.calls})"
        )
        # Execution count
        assert len(result.tool_executions) == 1
        exec0 = result.tool_executions[0]
        # Tool name
        assert exec0.tool_call.name == "read_paim12_probe"
        # Tool arguments
        assert exec0.tool_call.arguments == {"token": token}
        # Typed output
        assert exec0.output.result == f"PAIM12-PROBE:{token}"
        # Tool-call ID binding
        assert exec0.tool_message.tool_name == "read_paim12_probe"
        assert exec0.tool_message.tool_call_id == exec0.tool_call.call_id
        assert f"PAIM12-PROBE:{token}" in exec0.tool_message.content
        # Terminal RESPOND
        assert result.outcome.kind is AgentOutcomeKind.RESPOND
        assert f"PAIM12-PROBE:{token}" in result.outcome.message

    def test_tool_sample_1(
        self,
        paim12_tool_runtime: tuple[PydanticAIAgentRuntime, Paim12ProbeState],
    ) -> None:
        runtime, state = paim12_tool_runtime
        before = state.calls
        t0 = time.perf_counter()
        result = self._run_tool(runtime, "live")
        duration = time.perf_counter() - t0
        TestP12L04ToolSmoke._durations.append(duration)
        print(f"\nPAIM12_TOOL_1={duration:.3f}s")
        self._assert_tool_result(result, "live", before=before, state=state)

    def test_tool_sample_2(
        self,
        paim12_tool_runtime: tuple[PydanticAIAgentRuntime, Paim12ProbeState],
    ) -> None:
        runtime, state = paim12_tool_runtime
        before = state.calls
        t0 = time.perf_counter()
        result = self._run_tool(runtime, "live")
        duration = time.perf_counter() - t0
        TestP12L04ToolSmoke._durations.append(duration)
        print(f"\nPAIM12_TOOL_2={duration:.3f}s")
        self._assert_tool_result(result, "live", before=before, state=state)

    def test_tool_sample_3(
        self,
        paim12_tool_runtime: tuple[PydanticAIAgentRuntime, Paim12ProbeState],
    ) -> None:
        runtime, state = paim12_tool_runtime
        before = state.calls
        t0 = time.perf_counter()
        result = self._run_tool(runtime, "live")
        duration = time.perf_counter() - t0
        TestP12L04ToolSmoke._durations.append(duration)
        print(f"\nPAIM12_TOOL_3={duration:.3f}s")
        self._assert_tool_result(result, "live", before=before, state=state)

    @classmethod
    def teardown_class(cls) -> None:
        vals = cls._durations
        if vals:
            print(f"\nPAIM12_TOOL_SECONDS={vals}")
            print(f"PAIM12_TOOL_MIN_SECONDS={min(vals):.3f}")
            print(f"PAIM12_TOOL_MEDIAN_SECONDS={statistics.median(vals):.3f}")
            print(f"PAIM12_TOOL_MAX_SECONDS={max(vals):.3f}")
            print("PAIM12_TOOL_RELIABILITY=3/3")
