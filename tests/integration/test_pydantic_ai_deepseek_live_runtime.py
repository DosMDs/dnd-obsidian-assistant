"""RM-04: durable opt-in live DeepSeek provider/runtime gate.

This is the repeatable maintenance gate for DeepSeek provider/runtime
compatibility (future Pydantic AI upgrades, DeepSeek API/model/profile/adapter
changes, pre-RM-05 product qualification).  It is **not** the RM-02
protocol-compatibility spike and **not** an RM-05 product candidate.

Activation
──────────

The gate runs only when ``DND_ASSISTANT_DEEPSEEK_LIVE=1`` is set.  Ordinary
``uv run pytest`` collects these tests and skips them before any config read,
credential read or network access.

    absent selector                        -> SKIP (normal suite unaffected)
    selector set, config/profile missing   -> FAIL before network
    selector set, wrong canonical profile  -> FAIL before network
    selector set, credential missing       -> FAIL before network
    real provider/runtime failure          -> FAIL, sanitized classification

Configuration (explicit, machine-local):

    DND_ASSISTANT_DEEPSEEK_LIVE=1
    DND_ASSISTANT_DEEPSEEK_CONFIG=<path-to-models.toml>
    DND_ASSISTANT_DEEPSEEK_AGENT_PROFILE=<profile-name>
    DEEPSEEK_API_KEY=<secret>

The selected profile must be the canonical AGENT identity
(``provider=deepseek``, ``model=deepseek-flash``, ``thinking=true``,
``reasoning_effort=high``, canonical base URL).  No other candidate is silently
substituted.

Durable selection command:

    uv run pytest -m "provider_upgrade and deepseek"

This selection excludes the historical RM-02 spike
(``test_pydantic_ai_deepseek_live_spike.py`` carries only the ``deepseek``
marker, not ``provider_upgrade``).

Request budget
──────────────

    D1  production dispatch + runtime, thinking/high, zero tools, terminal RESPOND   1 request
    D2  production dispatch + runtime, thinking/high, one READ probe + continuation   2 requests
    ----------------------------------------------------------------------------------------
    total maximum                                                                    3 requests
    retries                                                                          0

No latency/performance samples and no product-v1.

Production path and lifecycle ownership
───────────────────────────────────────

Both cases use the real production-sensitive path: ``_load_profile`` ->
``_build_agent_model`` -> ``build_pydantic_ai_deepseek_model`` ->
``PydanticAIAgentRuntime`` (real dispatch, factory, credential boundary,
runtime, ExternalToolset/deferred continuation).  The context builder is a
synthetic double and the context contains no Vault/campaign data.  No WRITE
tool exists in the fixture.

The injected ``httpx2.AsyncClient`` carrying the sanitized ``LiveRequestRecorder``
is **caller-owned test infrastructure**, not a claim about production ownership.
It is closed explicitly in deterministic test cleanup and is never used as
provider-lifecycle evidence.  The authoritative proof that provider-owned
Ollama/DeepSeek clients close through the RM-03 managed ``Agent``/``Model``
context is the offline ``provider_upgrade`` module
``tests/unit/test_pydantic_ai_agent_runtime_lifecycle.py``.

Structural evidence only: request index, tools presence/count,
``tool_choice`` category, assistant ``reasoning_content`` presence (bool),
``tool_call_id`` association and handler counts.  Reasoning text, prompts, raw
bodies, headers (including ``Authorization``) and credential values are never
read, printed or persisted.
"""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx2
import pytest
from pydantic import BaseModel
from pydantic_ai.providers.deepseek import DeepSeekProvider

from dnd_assistant.application.agent_contracts import AgentOutcomeKind
from dnd_assistant.application.pydantic_ai_agent_runtime import PydanticAIAgentRuntime
from dnd_assistant.application.pydantic_ai_run_deps import DndAgentRunPreparer
from dnd_assistant.application.pydantic_ai_tool_bridge import PydanticAIToolBridge
from dnd_assistant.cli.agent_runtime import _build_agent_model, _load_profile
from dnd_assistant.errors import CredentialError, DndAssistantError
from dnd_assistant.models import pydantic_ai_deepseek as deepseek_module
from dnd_assistant.models.credentials import resolve_provider_api_key
from dnd_assistant.models.profiles import ModelProfile, ModelProfileRole, ReasoningEffort
from dnd_assistant.tools.catalog import build_tool_registry_schema
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import Permission, SessionMode
from dnd_assistant.tools.types import ToolDefinition as ProjectToolDefinition
from tests.support.context_builder_doubles import make_stub_context_builder
from tests.support.deepseek_errors import classify_provider_failure
from tests.support.deepseek_transport import LiveRequestRecorder
from tests.support.pydantic_ai_runtime import make_read_context

pytestmark = [pytest.mark.provider_upgrade, pytest.mark.deepseek]

_ENV_SELECTOR = "DND_ASSISTANT_DEEPSEEK_LIVE"
_ENV_CONFIG = "DND_ASSISTANT_DEEPSEEK_CONFIG"
_ENV_PROFILE = "DND_ASSISTANT_DEEPSEEK_AGENT_PROFILE"

_CANONICAL_MODEL = "deepseek-flash"
_CANONICAL_BASE_URL = "https://api.deepseek.com"
_PROBE_TOOL = "read_deepseek_probe"

_MAX_REQUESTS_D1 = 1
_MAX_REQUESTS_D2 = 2
_MAX_REQUESTS_TOTAL = _MAX_REQUESTS_D1 + _MAX_REQUESTS_D2

_DIRECT_PROMPT = (
    'Reply with exactly this JSON object and nothing else: {"kind":"respond","message":"pong"}'
)
_TOOL_PROMPT = (
    f'Use {_PROBE_TOOL} exactly once with token "alpha". Do not guess the probe '
    "result. After the tool returns, reply with a single JSON object "
    '{"kind":"respond","message":"<the exact probe result>"}.'
)


class DeepSeekProbeInput(BaseModel):
    token: str


class DeepSeekProbeOutput(BaseModel):
    result: str


@dataclass(frozen=True)
class LiveContext:
    profile: ModelProfile
    profile_name: str


def _record_client(recorder: LiveRequestRecorder) -> httpx2.AsyncClient:
    """Build the caller-owned observing client for one live case."""
    return httpx2.AsyncClient(
        timeout=httpx2.Timeout(60.0, connect=10.0),
        event_hooks={"request": [recorder]},
    )


def _close_client(client: httpx2.AsyncClient) -> None:
    """Deterministically dispose the caller-owned observing client.

    The client's live connection was opened inside the production runtime's own
    event loop, which ``PydanticAIAgentRuntime.run`` closes before returning.
    The injected client is caller-owned test infrastructure (the provider does
    not own an injected ``http_client``), so it is closed here.  Teardown of an
    already-dead loop means the socket was disposed with the loop; that specific
    dead-loop error is treated as completed disposal and not re-raised.
    """
    if client.is_closed:
        return
    try:
        asyncio.run(client.aclose())
    except RuntimeError as exc:
        if "Event loop is closed" not in str(exc):
            raise


def _validate_canonical_profile(profile: ModelProfile, profile_name: str) -> None:
    """Fail before network on any non-canonical live profile."""
    problems: list[str] = []
    if profile.provider != "deepseek":
        problems.append(f"provider={profile.provider!r}")
    if profile.role is not ModelProfileRole.AGENT:
        problems.append(f"role={profile.role.value!r}")
    if profile.model != _CANONICAL_MODEL:
        problems.append(f"model={profile.model!r}")
    if profile.thinking is not True:
        problems.append(f"thinking={profile.thinking!r}")
    if profile.reasoning_effort is not ReasoningEffort.HIGH:
        problems.append(f"reasoning_effort={profile.reasoning_effort!r}")
    if profile.base_url.rstrip("/") != _CANONICAL_BASE_URL:
        problems.append(f"base_url={profile.base_url!r}")
    if problems:
        pytest.fail(
            f"DeepSeek live profile {profile_name!r} is not the canonical "
            f"qualification identity: {', '.join(problems)}"
        )


@pytest.fixture(scope="module")
def live_context() -> LiveContext:
    """Resolve and validate the explicit machine-local live configuration.

    Skips before any config/credential/network access when the selector is
    absent.  Fails (never skips) when the selector is set but the required
    local configuration is missing or non-canonical.
    """
    if os.environ.get(_ENV_SELECTOR) != "1":
        pytest.skip(f"set {_ENV_SELECTOR}=1 to run the durable DeepSeek live gate")

    raw_config = os.environ.get(_ENV_CONFIG)
    if not raw_config:
        pytest.fail(f"{_ENV_SELECTOR}=1 but {_ENV_CONFIG} is missing or empty")

    profile_name = os.environ.get(_ENV_PROFILE)
    if not profile_name:
        pytest.fail(f"{_ENV_SELECTOR}=1 but {_ENV_PROFILE} is missing or empty")

    config_path = Path(raw_config)
    if not config_path.exists():
        pytest.fail(f"{_ENV_CONFIG} points to a missing file: {config_path}")

    try:
        profile = _load_profile(config_path, profile_name)
    except DndAssistantError as exc:
        pytest.fail(
            f"DeepSeek live gate could not load profile {profile_name!r} ({type(exc).__name__})"
        )

    _validate_canonical_profile(profile, profile_name)

    try:
        resolve_provider_api_key("deepseek")
    except CredentialError as exc:  # text names the env var, never the value
        pytest.fail(f"DeepSeek live gate credential unavailable: {exc}")

    return LiveContext(profile=profile, profile_name=profile_name)


def _build_registry(counter: list[str]) -> ToolRegistry:
    registry = ToolRegistry()

    def handler(inp: DeepSeekProbeInput, ctx: object) -> DeepSeekProbeOutput:
        counter.append(inp.token)
        return DeepSeekProbeOutput(result=f"probe-{inp.token}")

    definition = ProjectToolDefinition(
        name=_PROBE_TOOL,
        description=(
            "Authoritative probe tool for RM-04 verification. "
            "Use this tool to obtain the requested probe value."
        ),
        input_schema=DeepSeekProbeInput,
        output_schema=DeepSeekProbeOutput,
        permission=Permission.READ,
        side_effects=frozenset(),
        allowed_session_modes=frozenset(
            {SessionMode.ACTIVE_SESSION, SessionMode.NO_ACTIVE_SESSION}
        ),
    )
    registry.register(definition, handler)
    return registry


def _run_live_case(
    context: LiveContext,
    registry: ToolRegistry,
    recorder: LiveRequestRecorder,
    prompt: str,
) -> Any:
    """Run one live case through the real production path.

    The real credential boundary and provider dispatch/factory are exercised;
    the caller-owned observing client is injected only as the provider's HTTP
    transport and is always closed in cleanup.
    """
    client = _record_client(recorder)
    real_provider = DeepSeekProvider

    def _observing_provider(*args: Any, **kwargs: Any) -> DeepSeekProvider:
        kwargs.setdefault("http_client", client)
        return real_provider(*args, **kwargs)

    catalog = build_tool_registry_schema(registry)
    bridge = PydanticAIToolBridge(registry=registry)
    preparer = DndAgentRunPreparer(
        context_builder=make_stub_context_builder(),
        tool_catalog=catalog,
        tool_bridge=bridge,
    )

    try:
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(deepseek_module, "DeepSeekProvider", _observing_provider)
            model = _build_agent_model(context.profile)
        runtime = PydanticAIAgentRuntime(run_preparer=preparer, model=model)
        try:
            return runtime.run(prompt, execution_context=make_read_context())
        except DndAssistantError as exc:
            pytest.fail(
                "DeepSeek live runtime failure: "
                f"{classify_provider_failure(exc)} "
                f"({type(exc).__name__})"
            )
    finally:
        _close_client(client)


def test_budget_declared() -> None:
    assert _MAX_REQUESTS_TOTAL == 3


# ── D1 — direct terminal, zero tools, 1 request ────────────────────────────


def test_d1_direct_terminal_live(live_context: LiveContext) -> None:
    recorder = LiveRequestRecorder()
    result = _run_live_case(live_context, ToolRegistry(), recorder, _DIRECT_PROMPT)

    assert recorder.count == _MAX_REQUESTS_D1
    assert result.outcome.kind is AgentOutcomeKind.RESPOND
    assert result.tool_executions == ()

    request = recorder.requests[0]
    assert request.model == _CANONICAL_MODEL
    assert request.thinking_present is True
    assert request.thinking_type == "enabled"
    assert request.reasoning_effort == "high"
    assert request.tools_present is False


# ── D2 — one READ continuation, 2 requests ─────────────────────────────────


def test_d2_read_tool_continuation_live(live_context: LiveContext) -> None:
    recorder = LiveRequestRecorder()
    invocations: list[str] = []
    registry = _build_registry(invocations)
    result = _run_live_case(live_context, registry, recorder, _TOOL_PROMPT)

    assert recorder.count == _MAX_REQUESTS_D2
    assert invocations == ["alpha"]
    assert len(result.tool_executions) == 1
    assert result.tool_executions[0].tool_call.name == _PROBE_TOOL
    assert result.tool_executions[0].tool_call.arguments == {"token": "alpha"}
    assert result.outcome.kind is AgentOutcomeKind.RESPOND

    first, second = recorder.requests
    assert first.tools_present is True
    assert first.tool_choice_present is True
    assert first.tool_choice_category == "auto"
    assert first.assistant_reasoning_content_present is False

    assert second.tools_present is True
    assert second.tool_choice_present is True
    assert second.tool_choice_category == "auto"
    assert second.assistant_reasoning_content_present is True
    assert second.tool_result_ids, "expected the matching tool result on request 2"

    # Sanitized evidence can never carry reasoning/prompt/credential content.
    evidence = "\n".join(request.safe_repr() for request in recorder.requests)
    assert "authorization" not in evidence.lower()
