"""Provider-neutral deterministic evaluation contracts.

DTOs, enums and observation value objects for deterministic model/runtime
evaluation.  This module belongs to the ``dnd_assistant.evals`` package and
imports the Python standard library only.  It must never import another
``dnd_assistant`` layer, Ollama, Pydantic AI, Textual, Typer or any concrete
model/provider.

WRITE classification is explicit data supplied by callers from trusted tool
permission metadata; it is never inferred from a tool-name prefix.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

# ── Canonical diagnostic serialization contract ────────────────────────────
# One provider-neutral definition shared by the writer (composition) and the
# schema-v3 decoder so the serialized token/bound invariant cannot drift.

MAX_CAUSE_CHAIN_LENGTH: int = 4
"""Maximum number of sanitized cause-chain tokens in a serialized diagnostic."""

REDACTED_TYPE_TOKEN: str = "<redacted>"
"""Fixed redaction token emitted when a name is not a safe type token."""

_TYPE_TOKEN_RE = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]{0,63}\Z")


def is_canonical_type_token(token: object) -> bool:
    """True iff ``token`` is a canonical serialized diagnostic type token.

    Canonical tokens are either the fixed redaction token or a bare Python
    identifier-shaped class name (ASCII letters/underscore then up to 63
    letters/digits/underscores).  Anything else (paths, URLs, prose, whitespace)
    is not part of the serialized contract.
    """
    if not isinstance(token, str):
        return False
    if token == REDACTED_TYPE_TOKEN:
        return True
    return _TYPE_TOKEN_RE.match(token) is not None


def sanitize_type_token(name: object) -> str:
    """Return ``name`` if it is a canonical type token, else the redaction token."""
    if isinstance(name, str) and _TYPE_TOKEN_RE.match(name) is not None:
        return name
    return REDACTED_TYPE_TOKEN


# ── Expected action vocabulary ─────────────────────────────────────────────


class ScenarioExpectationKind(StrEnum):
    """Expected action kind for a decision scenario."""

    RESPOND_NO_TOOL = "respond_no_tool"
    CLARIFY_NO_TOOL = "clarify_no_tool"
    EXACT_TOOL_CALLS = "exact_tool_calls"
    NO_TOOL_ANY_TERMINAL = "no_tool_any_terminal"


# ── Scenario definition ────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ExpectedToolCall:
    """Expected exact tool call in a decision scenario.

    Args:
        tool_name: Exact expected tool name.
        arguments: Exact expected JSON-serialisable arguments dict.
        is_write: Explicit caller-supplied WRITE classification derived from
            trusted tool permission metadata.  Never inferred from the tool
            name.
    """

    tool_name: str
    arguments: dict[str, Any]
    is_write: bool = False


@dataclass(frozen=True, slots=True)
class EvalExpectation:
    """Deterministic expectation for one decision scenario.

    Args:
        kind: The expected action kind.
        tool_calls: Expected tool calls (for ``EXACT_TOOL_CALLS``).
        order_sensitive: Whether tool-call order matters.  ``False`` means the
            observed call multiset must match the expected call multiset.
    """

    kind: ScenarioExpectationKind
    tool_calls: tuple[ExpectedToolCall, ...] = ()
    order_sensitive: bool = True


@dataclass(frozen=True, slots=True)
class EvalScenario:
    """One deterministic eval scenario.

    Args:
        scenario_id: Stable unique scenario ID.
        user_input: The user query string.
        expectation: The expected outcome.
        description: Human-readable description of the scenario.
        hidden_write_expected: Whether WRITE-capable tools are expected to be
            hidden/unexposed for this scenario.  Explicit flag; never derived
            from description text or tool names.
    """

    scenario_id: str
    user_input: str
    expectation: EvalExpectation
    description: str = ""
    hidden_write_expected: bool = False


# ── Failure diagnostic vocabulary (schema v3) ──────────────────────────────


class FailureDiagnosticStatus(StrEnum):
    """Availability of per-sample failure diagnostics.

    ``NOT_AVAILABLE`` is the explicit empty value used for successful samples
    and for legacy schema-v2 reports that never carried diagnostics.
    """

    NOT_AVAILABLE = "not_available"
    OBSERVED = "observed"


class FailureSourceCategory(StrEnum):
    """Bounded, provider-neutral category of a runtime failure.

    ``MODEL_REQUEST`` means the wrapped semantic model request raised.
    ``FRAMEWORK_PROCESSING`` means the framework failed after a request
    returned (surfacing only through the project error cause chain).
    ``PROJECT_POLICY`` means the trusted project layer rejected the run.
    ``RUNTIME_OTHER`` is the bounded catch-all.
    """

    MODEL_REQUEST = "model_request"
    FRAMEWORK_PROCESSING = "framework_processing"
    PROJECT_POLICY = "project_policy"
    RUNTIME_OTHER = "runtime_other"


@dataclass(frozen=True, slots=True)
class FailureDiagnostic:
    """Bounded, sanitized per-sample failure evidence (provider-neutral).

    Only structured, non-secret evidence is retained: a source category, the
    sanitized exception type name, a bounded chain of sanitized cause type
    names, and the semantic request index when literally known.  Raw provider
    response bodies and human-readable exception messages are never persisted.

    Args:
        status: Whether a diagnostic is present.
        source_category: The bounded failure stage, or ``None`` when
            unavailable.
        exception_type: Sanitized exception class name, or ``None``.
        cause_chain: Bounded ordered sanitized cause type names.
        request_index: Zero-based semantic request index, or ``None``.
    """

    status: FailureDiagnosticStatus = FailureDiagnosticStatus.NOT_AVAILABLE
    source_category: FailureSourceCategory | None = None
    exception_type: str | None = None
    cause_chain: tuple[str, ...] = ()
    request_index: int | None = None


FAILURE_DIAGNOSTIC_NOT_AVAILABLE = FailureDiagnostic()
"""Explicit empty diagnostic for successful and legacy samples."""


# ── Exposure / observation DTOs ────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class ExposedToolInfo:
    """Snapshot of which tools were visible to the model for a turn.

    Args:
        tool_names: Tuple of exposed tool names in exposure order.
        has_write: Whether any exposed tool is WRITE-capable.  Explicit
            caller-supplied snapshot derived from trusted tool permission
            metadata; never inferred from tool names.
    """

    tool_names: tuple[str, ...]
    has_write: bool


@dataclass(frozen=True, slots=True)
class ToolCallObservation:
    """Observed tool call from a model decision.

    Args:
        tool_name: The tool name emitted by the model.
        arguments: The raw arguments dict (may be malformed).
        call_id: The tool call ID if available.
        schema_valid: Whether the arguments pass schema validation.
        is_write: Whether the emitted call targets a WRITE-capable tool, as
            supplied by the collector from trusted tool permission metadata.
            Never inferred from the tool name.
    """

    tool_name: str
    arguments: dict[str, Any]
    call_id: str | None
    schema_valid: bool
    is_write: bool = False


@dataclass(frozen=True, slots=True)
class DecisionObservation:
    """Observation of one model decision step.

    Args:
        scenario_id: The scenario ID this observation belongs to.
        repetition: The repetition number (0-indexed).
        duration_seconds: Wall-clock duration of the decision.
        tool_calls: Observed tool calls (empty if none).
        terminal_kind: Observed terminal kind.
        terminal_content: The assistant text content (may be None).
        exposed_tools: Snapshot of tools visible to the model for this turn.
        error_type: Error type string if an exception occurred, else None.
        error_message: Error message if an exception occurred, else None.
    """

    scenario_id: str
    repetition: int
    duration_seconds: float
    tool_calls: tuple[ToolCallObservation, ...] = ()
    terminal_kind: str | None = None
    terminal_content: str | None = None
    exposed_tools: ExposedToolInfo | None = None
    error_type: str | None = None
    error_message: str | None = None


@dataclass(frozen=True, slots=True)
class FullTurnObservation:
    """Observation of one full-turn runtime execution.

    Args:
        scenario_id: The scenario ID this observation belongs to.
        repetition: The repetition number (0-indexed).
        duration_seconds: Wall-clock duration of the full turn.
        success: Whether the turn completed without error.
        terminal_kind: The terminal outcome kind (RESPOND/CLARIFY).
        initial_tool_calls: The exact tool calls emitted in the first model
            response, with names and arguments.
        executed_tool_calls: The exact tool calls that were actually executed,
            with names and arguments.
        tool_call_count: Number of initial tool calls emitted.
        tool_execution_count: Number of tool executions performed.
        model_request_count: Number of semantic model requests.
        handler_call_count: Total number of handler invocations.
        write_handler_count: Number of WRITE handler invocations (literal
            execution evidence).
        exposed_tools: Snapshot of tools visible to the model for this turn.
        error_type: Error type string if an exception occurred, else None.
        error_message: Error message if an exception occurred, else None.
        failure_diagnostic: Bounded structured failure evidence for this
            sample (schema v3).  Explicit not-available for success/legacy v2.
    """

    scenario_id: str
    repetition: int
    duration_seconds: float
    success: bool
    terminal_kind: str | None = None
    initial_tool_calls: tuple[ToolCallObservation, ...] = ()
    executed_tool_calls: tuple[ToolCallObservation, ...] = ()
    tool_call_count: int = 0
    tool_execution_count: int = 0
    model_request_count: int = 0
    handler_call_count: int = 0
    write_handler_count: int = 0
    exposed_tools: ExposedToolInfo | None = None
    error_type: str | None = None
    error_message: str | None = None
    failure_diagnostic: FailureDiagnostic = field(default_factory=FailureDiagnostic)
