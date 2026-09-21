"""RM-02: opt-in live DeepSeek protocol compatibility spike.

This module is the explicit, bounded, paid live confirmation of the RM-02
offline findings.  It is **not** the durable RM-04 provider gate and **not** an
RM-05 product candidate.

Activation
──────────

The spike runs only when the explicit selector ``DND_ASSISTANT_DEEPSEEK_LIVE=1``
is set **and** the machine-local ``DEEPSEEK_API_KEY`` resolves.  Ordinary
``uv run pytest`` collects these tests and skips them before any network access
or credential read.

    absent selector                     -> skip (normal suite unaffected)
    selector set, credential missing     -> FAIL clearly (never silently skip)
    selector set, credential present     -> run

Hard request budget
───────────────────

    Case A  thinking enabled  / no tool    1 model HTTP request
    Case B  thinking disabled / no tool    1 model HTTP request
    Case C  thinking enabled  / READ tool  2 model HTTP requests
    ----------------------------------------------------------
    total maximum                          4 model HTTP requests

No automatic retries are configured.  The live tests use synthetic,
non-sensitive prompts and a spike-local deterministic READ tool only: no Vault,
no campaign context, no ToolExecutor, no WRITE tools, no product-v1.

Sanitized outbound evidence
───────────────────────────

Each real outbound request is projected through the same allowlisted
:func:`tests.support.deepseek_transport.project_request` used by the offline
tests.  The in-memory evidence therefore carries only structural facts (request
index, tools presence, ``tool_choice`` category, assistant ``reasoning_content``
presence as a bool, and ``tool_call_id`` association).  Reasoning text, prompts,
raw bodies, headers (including ``Authorization``) and API keys are never read
into evidence, printed, or persisted.  Diagnostics on failure are structural and
sanitized only.

Hidden reasoning is never printed or persisted; the spike asserts only presence,
part type and length.
"""

from __future__ import annotations

import os
from typing import Any

import httpx2
import pytest
from pydantic_ai import Agent
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError
from pydantic_ai.messages import ThinkingPart
from pydantic_ai.providers.deepseek import DeepSeekProvider

from dnd_assistant.errors import CredentialError
from dnd_assistant.models.credentials import resolve_provider_api_key
from dnd_assistant.models.profiles import ModelProfile, ModelProfileRole, ReasoningEffort
from dnd_assistant.models.pydantic_ai_deepseek import build_pydantic_ai_deepseek_model
from tests.support.deepseek_transport import LiveRequestRecorder

pytestmark = pytest.mark.deepseek

_SELECTOR_ENV = "DND_ASSISTANT_DEEPSEEK_LIVE"
_MAX_REQUESTS_PER_CASE = {"a": 1, "b": 1, "c": 2}


def _selected() -> bool:
    return os.environ.get(_SELECTOR_ENV) == "1"


@pytest.fixture(scope="module")
def deepseek_api_key() -> str:
    """Resolve the machine-local DeepSeek credential, or skip/fail explicitly."""
    if not _selected():
        pytest.skip(f"set {_SELECTOR_ENV}=1 to run the opt-in DeepSeek live spike")
    try:
        return resolve_provider_api_key("deepseek").get_secret_value()
    except CredentialError as exc:  # text never contains the secret value
        pytest.fail(
            f"DeepSeek live spike explicitly requested but credential is unavailable: {exc}"
        )


def _profile(*, thinking: bool, effort: ReasoningEffort | None) -> ModelProfile:
    return ModelProfile(
        provider="deepseek",
        model="deepseek-flash",
        base_url="https://api.deepseek.com",
        role=ModelProfileRole.AGENT,
        thinking=thinking,
        reasoning_effort=effort,
    )


def _recording_client(recorder: LiveRequestRecorder) -> httpx2.AsyncClient:
    return httpx2.AsyncClient(
        timeout=httpx2.Timeout(60.0, connect=10.0),
        event_hooks={"request": [recorder]},
    )


def _live_agent(
    api_key: str,
    profile: ModelProfile,
    recorder: LiveRequestRecorder,
    *,
    tools: list[Any] | None = None,
) -> Agent[None, str]:
    provider = DeepSeekProvider(api_key=api_key, http_client=_recording_client(recorder))
    model = build_pydantic_ai_deepseek_model(profile, provider=provider)
    return Agent(
        model,
        output_type=str,
        tools=tools or [],
        retries={"tools": 0, "output": 0},
    )


def _run(agent: Agent[None, str], prompt: str) -> Any:
    """Run one agent conversation, surfacing sanitized provider failures only."""
    try:
        return agent.run_sync(prompt)
    except ModelHTTPError as exc:
        # Never include the provider body, which may echo request content.
        pytest.fail(f"DeepSeek provider HTTP failure (status={exc.status_code})")
    except ModelAPIError as exc:
        pytest.fail(f"DeepSeek provider API failure ({type(exc).__name__})")


def _thinking_content_lengths(result: Any) -> list[int]:
    lengths: list[int] = []
    for message in result.all_messages():
        for part in getattr(message, "parts", ()):
            if isinstance(part, ThinkingPart):
                lengths.append(len(part.content or ""))
    return lengths


# ── Case A — thinking enabled, no tools ─────────────────────────────────────


def test_case_a_thinking_enabled_no_tool(deepseek_api_key: str) -> None:
    recorder = LiveRequestRecorder()
    agent = _live_agent(
        deepseek_api_key,
        _profile(thinking=True, effort=ReasoningEffort.HIGH),
        recorder,
    )

    result = _run(agent, "Reply with the single lowercase word: pong")

    assert recorder.count == _MAX_REQUESTS_PER_CASE["a"]
    assert isinstance(result.output, str)
    assert result.output.strip()


# ── Case B — thinking disabled, no tools ────────────────────────────────────


def test_case_b_thinking_disabled_no_tool(deepseek_api_key: str) -> None:
    recorder = LiveRequestRecorder()
    agent = _live_agent(
        deepseek_api_key,
        _profile(thinking=False, effort=None),
        recorder,
    )

    result = _run(agent, "Reply with the single lowercase word: pong")

    assert recorder.count == _MAX_REQUESTS_PER_CASE["b"]
    assert isinstance(result.output, str)
    assert result.output.strip()


# ── Case C — thinking enabled + one deterministic READ continuation ─────────


def test_case_c_thinking_read_tool_continuation(deepseek_api_key: str) -> None:
    recorder = LiveRequestRecorder()
    tool_invocations: list[str] = []

    def read_probe(key: str) -> str:
        """Read a deterministic synthetic probe value by key."""
        tool_invocations.append(key)
        return "probe-42"

    agent = _live_agent(
        deepseek_api_key,
        _profile(thinking=True, effort=ReasoningEffort.HIGH),
        recorder,
        tools=[read_probe],
    )

    result = _run(
        agent,
        "Call the read_probe tool with key='alpha'. Then reply with the exact "
        "value the tool returned.",
    )

    # Exactly two model HTTP requests: the tool-calling turn and its continuation.
    assert recorder.count == _MAX_REQUESTS_PER_CASE["c"]
    assert tool_invocations == ["alpha"]
    assert isinstance(result.output, str)
    assert "probe-42" in result.output

    first, second = recorder.requests

    # Request 1 carried tools with a DeepSeek-valid (unforced) tool choice.
    assert first.tools_present is True
    assert first.tool_choice_present is True
    assert first.tool_choice_category == "auto"
    assert first.assistant_reasoning_content_present is False

    # Request 2 replayed the assistant reasoning_content and associated the tool
    # result while keeping the unforced tool choice.
    assert second.tools_present is True
    assert second.tool_choice_present is True
    assert second.tool_choice_category == "auto"
    assert second.assistant_reasoning_content_present is True
    assert second.tool_result_ids, "expected the matching tool result on request 2"

    # The provider reasoning reached the framework as a non-empty ThinkingPart;
    # assert presence/length only, never text.
    lengths = _thinking_content_lengths(result)
    assert lengths, "expected provider reasoning to convert to a ThinkingPart"
    assert any(length > 0 for length in lengths)


# ── Credential path through the factory (zero model requests) ───────────────


def test_factory_credential_resolution_succeeds(deepseek_api_key: str) -> None:
    """The factory's own credential path builds a model without any request.

    No agent is run here, so this test makes **zero** model HTTP requests; it
    only exercises the credential-construction boundary.
    """
    model = build_pydantic_ai_deepseek_model(_profile(thinking=True, effort=ReasoningEffort.HIGH))
    assert model.model_name == "deepseek-flash"
