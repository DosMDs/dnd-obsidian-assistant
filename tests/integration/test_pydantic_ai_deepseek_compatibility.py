"""RM-02: DeepSeek protocol compatibility — deterministic offline request tests.

These tests exercise the RM-02 DeepSeek factory through real Pydantic AI
``Agent`` runs whose HTTP transport is a sanitized recording mock.  They prove
the outbound wire shape (thinking toggle, reasoning effort, tools, tool_choice)
and the ``reasoning_content`` round-trip across a tool continuation, without any
real network access, credential or persisted hidden reasoning.

No test here requires ``DEEPSEEK_API_KEY`` and none performs a real request.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic_ai import Agent
from pydantic_ai.messages import ThinkingPart
from pydantic_ai.providers.deepseek import DeepSeekProvider

from dnd_assistant.models.profiles import ModelProfile, ModelProfileRole, ReasoningEffort
from dnd_assistant.models.pydantic_ai_deepseek import build_pydantic_ai_deepseek_model
from tests.support.deepseek_transport import (
    DeepSeekTransportCapture,
    deepseek_chat_completion,
)

_OFFLINE_DUMMY_KEY = "offline-dummy-key"
_REASONING_TEXT = "synthetic-reasoning-text"


def _profile(
    *, thinking: bool = True, effort: ReasoningEffort | None = ReasoningEffort.HIGH
) -> ModelProfile:
    return ModelProfile(
        provider="deepseek",
        model="deepseek-flash",
        base_url="https://api.deepseek.com",
        role=ModelProfileRole.AGENT,
        thinking=thinking,
        reasoning_effort=effort,
    )


def read_probe(key: str) -> str:
    """Read a deterministic synthetic probe value by key."""
    return f"probe::{key}"


def _tool_call_dict() -> dict[str, Any]:
    return {
        "id": "call-1",
        "type": "function",
        "function": {"name": "read_probe", "arguments": '{"key":"alpha"}'},
    }


def _build_model(capture: DeepSeekTransportCapture, profile: ModelProfile):
    provider = DeepSeekProvider(
        api_key=_OFFLINE_DUMMY_KEY,
        http_client=capture.client(),
    )
    return build_pydantic_ai_deepseek_model(profile, provider=provider)


def _all_safe_reprs(capture: DeepSeekTransportCapture) -> str:
    return "\n".join(request.safe_repr() for request in capture.requests)


# ── Case A — plain thinking response, no tools ──────────────────────────────


class TestCaseAPlainThinkingResponse:
    def test_request_shape_and_terminal_output(self) -> None:
        capture = DeepSeekTransportCapture([deepseek_chat_completion(content="hello")])
        model = _build_model(capture, _profile())
        agent = Agent(
            model,
            output_type=str,
            retries={"tools": 0, "output": 0},
        )

        result = agent.run_sync("Say hello.")

        assert capture.request_count == 1
        request = capture.requests[0]
        assert request.model == "deepseek-flash"
        assert request.thinking_present is True
        assert request.thinking_type == "enabled"
        assert request.reasoning_effort == "high"
        assert request.tools_present is False
        assert request.tool_choice_present is False
        assert result.output == "hello"


# ── Case B — thinking disabled ──────────────────────────────────────────────


class TestCaseBThinkingDisabled:
    def test_request_shape_and_terminal_output(self) -> None:
        capture = DeepSeekTransportCapture([deepseek_chat_completion(content="ok")])
        model = _build_model(capture, _profile(thinking=False, effort=None))
        agent = Agent(
            model,
            output_type=str,
            retries={"tools": 0, "output": 0},
        )

        result = agent.run_sync("Say ok.")

        assert capture.request_count == 1
        request = capture.requests[0]
        assert request.thinking_present is True
        assert request.thinking_type == "disabled"
        assert request.reasoning_effort is None
        assert request.tools_present is False
        assert result.output == "ok"


# ── Case C — thinking + one READ tool continuation ──────────────────────────


class TestCaseCThinkingToolContinuation:
    def test_full_round_trip(self) -> None:
        capture = DeepSeekTransportCapture(
            [
                deepseek_chat_completion(
                    reasoning_content=_REASONING_TEXT,
                    tool_calls=[_tool_call_dict()],
                ),
                deepseek_chat_completion(content="done"),
            ]
        )
        model = _build_model(capture, _profile())
        agent = Agent(
            model,
            output_type=str,
            tools=[read_probe],
            retries={"tools": 0, "output": 0},
        )

        result = agent.run_sync("Call read_probe with key='alpha', then report the value.")

        assert capture.request_count == 2

        first = capture.requests[0]
        assert first.model == "deepseek-flash"
        assert first.thinking_present is True
        assert first.thinking_type == "enabled"
        assert first.reasoning_effort == "high"
        assert first.tools_present is True
        assert first.tools_count == 1
        assert first.tool_choice_present is True
        assert first.tool_choice_category == "auto"
        assert first.assistant_reasoning_content_present is False

        second = capture.requests[1]
        assert second.tools_present is True
        assert second.tool_choice_present is True
        assert second.tool_choice_category == "auto"
        assert second.assistant_reasoning_content_present is True
        assert second.tool_result_ids == ("call-1",)

        assert result.output == "done"

    def test_reasoning_converted_to_thinking_part_but_not_output(self) -> None:
        capture = DeepSeekTransportCapture(
            [
                deepseek_chat_completion(
                    reasoning_content=_REASONING_TEXT,
                    tool_calls=[_tool_call_dict()],
                ),
                deepseek_chat_completion(content="done"),
            ]
        )
        model = _build_model(capture, _profile())
        agent = Agent(
            model,
            output_type=str,
            tools=[read_probe],
            retries={"tools": 0, "output": 0},
        )

        result = agent.run_sync("Call read_probe with key='alpha', then report the value.")

        thinking_parts = [
            part
            for message in result.all_messages()
            for part in getattr(message, "parts", ())
            if isinstance(part, ThinkingPart)
        ]
        assert thinking_parts, "expected the provider reasoning to convert to a ThinkingPart"
        assert any(part.content == _REASONING_TEXT for part in thinking_parts)
        assert _REASONING_TEXT not in result.output


# ── Sanitized evidence / no-leak guarantees ─────────────────────────────────


class TestSanitizedEvidence:
    def test_evidence_never_contains_reasoning_prompt_or_credentials(self) -> None:
        capture = DeepSeekTransportCapture(
            [
                deepseek_chat_completion(
                    reasoning_content=_REASONING_TEXT,
                    tool_calls=[_tool_call_dict()],
                ),
                deepseek_chat_completion(content="done"),
            ]
        )
        model = _build_model(capture, _profile())
        agent = Agent(
            model,
            output_type=str,
            tools=[read_probe],
            retries={"tools": 0, "output": 0},
        )

        agent.run_sync("Call read_probe with key='alpha', then report the value.")

        evidence = _all_safe_reprs(capture)
        assert _REASONING_TEXT not in evidence
        assert _OFFLINE_DUMMY_KEY not in evidence
        assert "authorization" not in evidence.lower()
        assert "read_probe with key" not in evidence  # no prompt text
        # Structural proof the continuation carried reasoning presence as a bool.
        assert capture.requests[1].assistant_reasoning_content_present is True


@pytest.mark.parametrize("effort", [ReasoningEffort.LOW, ReasoningEffort.HIGH, ReasoningEffort.MAX])
def test_all_canonical_efforts_reach_wire(effort: ReasoningEffort) -> None:
    capture = DeepSeekTransportCapture([deepseek_chat_completion(content="ok")])
    model = _build_model(capture, _profile(thinking=True, effort=effort))
    agent = Agent(model, output_type=str, retries={"tools": 0, "output": 0})

    agent.run_sync("Say ok.")

    assert capture.requests[0].reasoning_effort == effort.value
    assert capture.requests[0].thinking_type == "enabled"
