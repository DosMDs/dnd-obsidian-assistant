"""RM-04: DeepSeek production-runtime offline preflight.

This module is the deterministic, offline mirror of the durable RM-04 live gate
(``test_pydantic_ai_deepseek_live_runtime.py``).  It drives the accepted
production-sensitive DeepSeek path with a sanitized recording mock transport:

    _load_profile(config, name)
        -> _build_agent_model(profile)
        -> build_pydantic_ai_deepseek_model(profile, provider=<mock>)
        -> PydanticAIAgentRuntime

It proves, without network or credential, that the production dispatch,
runtime, ExternalToolset/deferred continuation and DeepSeek
``reasoning_content`` replay behave as the live gate requires.  It also carries
deterministic secret-safety tests for the sanitized failure classifier.

No Vault, no WRITE tool, no product-v1.  This module is part of the curated
``provider_upgrade`` selection.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel
from pydantic_ai.exceptions import ModelAPIError, ModelHTTPError
from pydantic_ai.providers.deepseek import DeepSeekProvider

from dnd_assistant.application.agent_contracts import AgentOutcomeKind
from dnd_assistant.application.pydantic_ai_agent_runtime import PydanticAIAgentRuntime
from dnd_assistant.application.pydantic_ai_run_deps import DndAgentRunPreparer
from dnd_assistant.application.pydantic_ai_tool_bridge import PydanticAIToolBridge
from dnd_assistant.cli.agent_runtime import _build_agent_model, _load_profile
from dnd_assistant.models import pydantic_ai_deepseek as deepseek_module
from dnd_assistant.models.profiles import ModelProfile
from dnd_assistant.tools.catalog import build_tool_registry_schema
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.types import Permission, SessionMode
from dnd_assistant.tools.types import ToolDefinition as ProjectToolDefinition
from tests.support.context_builder_doubles import make_stub_context_builder
from tests.support.deepseek_errors import classify_provider_failure
from tests.support.deepseek_transport import (
    DeepSeekTransportCapture,
    deepseek_chat_completion,
)
from tests.support.pydantic_ai_runtime import make_read_context

pytestmark = pytest.mark.provider_upgrade

_OFFLINE_DUMMY_KEY = "offline-dummy-key"
_REASONING_TEXT = "synthetic-reasoning-text"
_PROBE_TOOL = "read_deepseek_probe"

_CANONICAL_TOML = """\
[profiles.agent-deepseek]
provider = "deepseek"
model = "deepseek-flash"
base_url = "https://api.deepseek.com"
role = "agent"
thinking = true
reasoning_effort = "high"
"""


class DeepSeekProbeInput(BaseModel):
    token: str


class DeepSeekProbeOutput(BaseModel):
    result: str


def _load_canonical_profile(tmp_path: Path) -> ModelProfile:
    path = tmp_path / "models.toml"
    path.write_text(_CANONICAL_TOML, encoding="utf-8")
    return _load_profile(path, "agent-deepseek")


def _read_probe_registry(counter: list[str]) -> ToolRegistry:
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


def _build_production_runtime(
    monkeypatch: pytest.MonkeyPatch,
    profile: ModelProfile,
    registry: ToolRegistry,
    responses: list[dict[str, Any]],
) -> tuple[PydanticAIAgentRuntime, DeepSeekTransportCapture]:
    """Build the real production runtime with a sanitized mock transport.

    The production credential boundary and the real provider dispatch/factory
    are exercised; only the HTTP transport is replaced with a recording mock
    that stores allowlisted projections (never bodies/headers/reasoning text).
    """
    monkeypatch.setenv("DEEPSEEK_API_KEY", _OFFLINE_DUMMY_KEY)
    capture = DeepSeekTransportCapture(responses)
    real_provider = DeepSeekProvider

    def _recording_provider(*args: Any, **kwargs: Any) -> DeepSeekProvider:
        kwargs.setdefault("http_client", capture.client())
        return real_provider(*args, **kwargs)

    monkeypatch.setattr(deepseek_module, "DeepSeekProvider", _recording_provider)

    catalog = build_tool_registry_schema(registry)
    bridge = PydanticAIToolBridge(registry=registry)
    preparer = DndAgentRunPreparer(
        context_builder=make_stub_context_builder(),
        tool_catalog=catalog,
        tool_bridge=bridge,
    )
    model = _build_agent_model(profile)
    runtime = PydanticAIAgentRuntime(run_preparer=preparer, model=model)
    return runtime, capture


# ── Production credential boundary (pre-request) ───────────────────────────


def test_production_dispatch_requires_credential(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The real dispatch/factory fails closed when the credential is absent."""
    from dnd_assistant.errors import CredentialError

    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    profile = _load_canonical_profile(tmp_path)
    with pytest.raises(CredentialError, match="DEEPSEEK_API_KEY"):
        _build_agent_model(profile)


# ── Direct terminal path — 1 model request ─────────────────────────────────


def test_production_runtime_direct_terminal(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    profile = _load_canonical_profile(tmp_path)
    responses = [deepseek_chat_completion(content='{"kind":"respond","message":"direct-ok"}')]
    runtime, capture = _build_production_runtime(monkeypatch, profile, ToolRegistry(), responses)

    result = runtime.run(
        "Return a terminal respond JSON whose message is exactly direct-ok.",
        execution_context=make_read_context(),
    )

    assert capture.request_count == 1
    assert result.outcome.kind is AgentOutcomeKind.RESPOND
    assert "direct-ok" in result.outcome.message
    assert result.tool_executions == ()

    request = capture.requests[0]
    assert request.model == "deepseek-flash"
    assert request.thinking_present is True
    assert request.thinking_type == "enabled"
    assert request.reasoning_effort == "high"
    assert request.tools_present is False


# ── READ-tool continuation path — 2 model requests ─────────────────────────


def test_production_runtime_read_tool_continuation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    profile = _load_canonical_profile(tmp_path)
    invocations: list[str] = []
    registry = _read_probe_registry(invocations)
    responses = [
        deepseek_chat_completion(
            reasoning_content=_REASONING_TEXT,
            tool_calls=[
                {
                    "id": "call-1",
                    "type": "function",
                    "function": {
                        "name": _PROBE_TOOL,
                        "arguments": '{"token":"alpha"}',
                    },
                }
            ],
        ),
        deepseek_chat_completion(content='{"kind":"respond","message":"probe-alpha"}'),
    ]
    runtime, capture = _build_production_runtime(monkeypatch, profile, registry, responses)

    result = runtime.run(
        f'Use {_PROBE_TOOL} exactly once with token "alpha", then reply with a '
        "terminal respond JSON whose message contains the exact probe marker.",
        execution_context=make_read_context(),
    )

    assert capture.request_count == 2
    assert invocations == ["alpha"]
    assert len(result.tool_executions) == 1
    assert result.tool_executions[0].tool_call.name == _PROBE_TOOL
    assert result.tool_executions[0].tool_call.arguments == {"token": "alpha"}
    assert result.outcome.kind is AgentOutcomeKind.RESPOND
    assert "probe-alpha" in result.outcome.message

    first, second = capture.requests
    assert first.tools_present is True
    assert first.tool_choice_present is True
    assert first.tool_choice_category == "auto"
    assert first.assistant_reasoning_content_present is False

    assert second.tools_present is True
    assert second.tool_choice_present is True
    assert second.tool_choice_category == "auto"
    assert second.assistant_reasoning_content_present is True
    assert second.tool_result_ids, "expected the matching tool result on request 2"

    # Reasoning text is never part of the captured projection.
    evidence = "\n".join(request.safe_repr() for request in capture.requests)
    assert _REASONING_TEXT not in evidence
    assert _OFFLINE_DUMMY_KEY not in evidence
    assert "authorization" not in evidence.lower()


def test_probe_registry_has_no_write_tool() -> None:
    registry = _read_probe_registry([])
    definitions = registry.list_definitions()
    assert {d.name for d in definitions} == {_PROBE_TOOL}
    assert all(d.permission is Permission.READ for d in definitions)


# ── Sanitized failure classification ───────────────────────────────────────


def test_http_status_classification_is_structural() -> None:
    secret = "sk-super-secret-value"
    exc = ModelHTTPError(401, "deepseek-flash", body={"error": secret})
    classified = classify_provider_failure(exc)
    assert classified == "AUTH (status=401)"
    assert secret not in classified


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (429, "RATE_LIMIT (status=429)"),
        (400, "PROVIDER_4XX (status=400)"),
        (503, "PROVIDER_5XX (status=503)"),
    ],
)
def test_http_status_categories(status: int, expected: str) -> None:
    assert classify_provider_failure(ModelHTTPError(status, "deepseek-flash")) == expected


def test_transport_and_api_classification() -> None:
    import httpx2

    assert classify_provider_failure(httpx2.ConnectError("boom")).startswith("NETWORK")
    assert classify_provider_failure(httpx2.ReadTimeout("slow")).startswith("TIMEOUT")
    assert (
        classify_provider_failure(ModelAPIError("deepseek-flash", "api boom"))
        == "PROVIDER_API (ModelAPIError)"
    )


def test_classifier_does_not_leak_exception_message() -> None:
    secret = "sk-super-secret-value"

    class _Leaky(Exception):
        status_code = 403

    leaky = _Leaky(secret)
    classified = classify_provider_failure(leaky)
    assert classified == "AUTH (status=403)"
    assert secret not in classified
    assert secret not in repr(classified)


def test_classifier_handles_unclassified_exception() -> None:
    assert classify_provider_failure(RuntimeError("x")) == "UNKNOWN (RuntimeError)"
