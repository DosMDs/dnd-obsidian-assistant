"""CLI compatibility re-export for the shared agent runtime composition (TUI-02).

The real agent-runtime composition and model lifetime now live in
``dnd_assistant.composition.agent_runtime`` /
``dnd_assistant.composition.agent_model``.  This module is a thin
presentation-side re-export kept only so existing CLI imports and tests keep
working; it contains no composition logic and is not the composition owner.

Monkeypatch targets that need the concrete owner classes (``AuditService``,
``ObsidianSessionMetadataRepository``, ``PydanticAIAgentRuntime``) must patch
``dnd_assistant.composition.agent_runtime`` instead of relying on names bound
here.
"""

from __future__ import annotations

from dnd_assistant.composition.agent_model import (
    _build_agent_model,
    _build_ask_audit_context,
    _load_profile,
    _new_operation_id,
    _now_utc,
)
from dnd_assistant.composition.agent_runtime import (
    AskRuntime,
    _build_ask_tool_registry,
    _derive_session_context,
    compose_ask_runtime,
)

__all__ = [
    "AskRuntime",
    "_build_agent_model",
    "_build_ask_audit_context",
    "_build_ask_tool_registry",
    "_derive_session_context",
    "_load_profile",
    "_new_operation_id",
    "_now_utc",
    "compose_ask_runtime",
]
