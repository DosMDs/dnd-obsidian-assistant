"""Bounded, sanitized eval failure diagnostics (S14-07-DIAG-02).

Concrete framework classification lives here (composition), never in the
provider-neutral ``dnd_assistant.evals`` package.  This module turns a failed
sample into a bounded :class:`FailureDiagnostic` that preserves enough
structure to distinguish future failures such as a provider/model request
exception, a Pydantic AI / ``AgentRunError`` framework-processing failure, a
project policy rejection, or another bounded runtime failure.

Privacy policy: only sanitized exception *class names*, a bounded cause-chain
of sanitized class names, a category and a request index are retained.  Raw
provider response bodies and human-readable messages are never persisted.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from pydantic_ai.exceptions import AgentRunError

from dnd_assistant.errors import DndAssistantError
from dnd_assistant.evals.contracts import (
    FailureDiagnostic,
    FailureDiagnosticStatus,
    FailureSourceCategory,
)

if TYPE_CHECKING:
    from dnd_assistant.composition.eval_model import ModelCallRecorder

MAX_CAUSE_CHAIN: int = 4
"""Maximum sanitized cause-chain entries retained per diagnostic."""

_REDACTED_TYPE_NAME = "<redacted>"
_TYPE_NAME_RE = re.compile(r"\A[A-Za-z_][A-Za-z0-9_]{0,63}\Z")


def sanitize_type_name(name: str) -> str:
    """Return ``name`` only when it is a safe bare Python class identifier.

    Anything else (spaces, paths, punctuation, over-long or non-ASCII) is
    replaced with a fixed redaction marker so no private text can leak through
    an exception class name.
    """
    if isinstance(name, str) and _TYPE_NAME_RE.match(name):
        return name
    return _REDACTED_TYPE_NAME


def bounded_cause_chain(exc: BaseException, *, limit: int = MAX_CAUSE_CHAIN) -> tuple[str, ...]:
    """Return a bounded chain of sanitized cause type names below ``exc``.

    Follows ``__cause__`` first and falls back to ``__context__`` at each step,
    with an identity guard, so the chain is linear, deterministic and bounded.
    """
    names: list[str] = []
    seen: set[int] = set()
    current = exc.__cause__ if exc.__cause__ is not None else exc.__context__
    while current is not None and len(names) < limit and id(current) not in seen:
        seen.add(id(current))
        names.append(sanitize_type_name(type(current).__name__))
        current = current.__cause__ if current.__cause__ is not None else current.__context__
    return tuple(names)


def _find_in_cause_chain(exc: BaseException, cls: type[BaseException]) -> BaseException | None:
    """Return the first instance of ``cls`` at or below ``exc``, else ``None``."""
    seen: set[int] = set()
    stack: list[BaseException] = [exc]
    while stack:
        current = stack.pop(0)
        if id(current) in seen:
            continue
        seen.add(id(current))
        if isinstance(current, cls):
            return current
        if current.__cause__ is not None:
            stack.append(current.__cause__)
        if current.__context__ is not None:
            stack.append(current.__context__)
    return None


def _observed(
    category: FailureSourceCategory,
    exception_type: str,
    cause_chain: tuple[str, ...],
    request_index: int | None,
) -> FailureDiagnostic:
    return FailureDiagnostic(
        status=FailureDiagnosticStatus.OBSERVED,
        source_category=category,
        exception_type=sanitize_type_name(exception_type),
        cause_chain=tuple(sanitize_type_name(entry) for entry in cause_chain),
        request_index=request_index,
    )


def build_failure_diagnostic(
    error: BaseException | None,
    recorder: ModelCallRecorder,
) -> FailureDiagnostic:
    """Build the bounded diagnostic for one completed (or failed) sample.

    Uses both evidence sources: exceptions literally observed at the wrapped
    model-request boundary (``recorder``) and the final project error cause
    chain (``error``), so framework failures that happen *after* a successful
    ``model.request()`` are not lost.
    """
    if error is None:
        return FailureDiagnostic()

    request_index = recorder.request_count - 1 if recorder.request_count > 0 else None

    # 1. A wrapped semantic model request raised: most precise evidence.
    if recorder.failure_records:
        last = recorder.failure_records[-1]
        return _observed(
            FailureSourceCategory.MODEL_REQUEST,
            last.exception_type,
            last.cause_chain,
            last.request_index,
        )

    # 2. A framework AgentRunError survived only through the project cause chain.
    agent_error = _find_in_cause_chain(error, AgentRunError)
    if agent_error is not None:
        return _observed(
            FailureSourceCategory.FRAMEWORK_PROCESSING,
            type(agent_error).__name__,
            bounded_cause_chain(agent_error),
            request_index,
        )

    # 3. A trusted project layer rejected the run (policy/validation/etc).
    if isinstance(error, DndAssistantError):
        return _observed(
            FailureSourceCategory.PROJECT_POLICY,
            type(error).__name__,
            bounded_cause_chain(error),
            request_index,
        )

    # 4. Bounded catch-all.
    return _observed(
        FailureSourceCategory.RUNTIME_OTHER,
        type(error).__name__,
        bounded_cause_chain(error),
        request_index,
    )
