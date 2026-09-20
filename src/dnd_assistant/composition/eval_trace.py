"""Bounded, opt-in, append-only local diagnostic trace for eval runs (DIAG-03).

``LOCAL_DIAGNOSTIC_TRACE`` is disposable operator evidence: it is **not**
campaign Source of Truth, **not** Vault content and **not** acceptance evidence.
Only the frozen ``EvalReport`` determines candidate acceptance.

Design
──────

- explicit caller-supplied path only: no default path, no discovery;
- append-only JSONL, UTF-8, sorted keys, ``ensure_ascii=False``, ``allow_nan=False``;
- one JSON line per event, flushed after every event; the file stays open for the
  trace lifetime;
- process-crash oriented: flush, not ``fsync``.  This is not power-loss /
  filesystem-crash durable audit storage;
- writer faults are recorded in trusted Python state and stop further writes;
  they never raise into model/runtime execution (see ``EvalTraceWriter.emit``);
- only allowlisted, sanitized structured fields are persisted; prompts, message
  content, terminal content, tool arguments, raw exception text, response
  bodies, headers, URLs and local paths are never written.

Open/validation failure (before any model request) is fail-closed and raises
:class:`EvalTraceError`; the CLI aborts before warm-up or measurement.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import IO, Any

from dnd_assistant.evals.contracts import (
    MAX_CAUSE_CHAIN_LENGTH,
    sanitize_type_token,
)

TRACE_SCHEMA_VERSION = 1

# ── Lifecycle event names ──────────────────────────────────────────────────

EVENT_TRACE_STARTED = "trace_started"
EVENT_WARMUP_STARTED = "warmup_started"
EVENT_WARMUP_COMPLETED = "warmup_completed"
EVENT_WARMUP_FAILED = "warmup_failed"
EVENT_MEASUREMENT_STARTED = "measurement_started"
EVENT_SAMPLE_STARTED = "sample_started"
EVENT_REQUEST_STARTED = "request_started"
EVENT_REQUEST_COMPLETED = "request_completed"
EVENT_REQUEST_FAILED = "request_failed"
EVENT_SAMPLE_COMPLETED = "sample_completed"
EVENT_MEASUREMENT_COMPLETED = "measurement_completed"
EVENT_REPORT_WRITTEN = "report_written"

# ── Phase discriminator ────────────────────────────────────────────────────

PHASE_PRE_RUN = "pre_run"
PHASE_WARMUP = "warmup"
PHASE_MEASUREMENT = "measurement"

TRACE_FAULT_MESSAGE = "diagnostic trace incomplete (local only; report unaffected)"

# ── Allowlisted field contract ─────────────────────────────────────────────
# Only these bounded structured fields may appear on a persisted event.  Any
# other field is a programming error and faults the writer rather than leaking
# arbitrary data.

_ALLOWED_EVENT_FIELDS: frozenset[str] = frozenset(
    {
        "phase",
        "scenario_id",
        "repetition",
        "request_index",
        "elapsed_seconds",
        "exception_type",
        "cause_chain",
        "source_category",
        "provider_http_status",
        "response_part_types",
        "tool_names",
        "success",
        "terminal_kind",
        "failure_status",
        "model_request_count",
        "tool_call_count",
        "handler_call_count",
        "write_handler_count",
        "runtime_mode",
        "runtime_label",
        "dataset_id",
        "dataset_version",
        "expected_sample_count",
        "prompt_version",
    }
)


class EvalTraceError(Exception):
    """Raised when the diagnostic trace cannot be opened before measurement."""


@dataclass(frozen=True, slots=True)
class EvalTraceFault:
    """Bounded classification of the first trace serialize/write failure."""

    stage: str
    exception_type: str


@dataclass(slots=True)
class EvalTraceWriter:
    """Append-only JSONL diagnostic trace for one eval run.

    A serialize or write failure marks the writer faulted and stops further
    trace writes.  It is never raised into model/runtime execution.
    """

    path: Path
    _handle: IO[str]
    fault: EvalTraceFault | None = None

    @property
    def faulted(self) -> bool:
        """True once a serialize or write failure has been observed."""
        return self.fault is not None

    def emit(self, event: str, /, **fields: Any) -> None:
        """Append one diagnostic event; never raises into the caller."""
        if self.fault is not None:
            return
        try:
            line = self._serialize(event, fields)
        except Exception as exc:  # noqa: BLE001 - trace must never alter semantics
            self._mark_fault("serialize", exc)
            return
        try:
            self._handle.write(line)
            self._handle.flush()
        except Exception as exc:  # noqa: BLE001 - trace must never alter semantics
            self._mark_fault("write", exc)

    def close(self) -> None:
        """Close the underlying handle, ignoring close failures."""
        try:
            self._handle.close()
        except Exception:  # noqa: BLE001 - close failure is not actionable
            pass

    def _mark_fault(self, stage: str, exc: BaseException) -> None:
        self.fault = EvalTraceFault(
            stage=stage,
            exception_type=sanitize_type_token(type(exc).__name__),
        )

    def _serialize(self, event: str, fields: Mapping[str, Any]) -> str:
        payload: dict[str, Any] = {
            "trace_schema_version": TRACE_SCHEMA_VERSION,
            "event": event,
        }
        for key, value in fields.items():
            if key not in _ALLOWED_EVENT_FIELDS:
                raise ValueError(f"trace field {key!r} is not allowlisted")
            payload[key] = _normalize_field(key, value)
        return json.dumps(payload, ensure_ascii=False, sort_keys=True, allow_nan=False) + "\n"


def _normalize_field(key: str, value: Any) -> Any:
    """Sanitize a single allowlisted trace field value.

    Type-name and name-list fields are always reduced to canonical sanitized
    tokens so a model/provider-supplied string can never carry arbitrary text
    into the trace.
    """
    if key == "exception_type":
        if value is None:
            return None
        return sanitize_type_token(value)
    if key == "cause_chain":
        if value is None:
            return []
        entries = list(value)
        if len(entries) > MAX_CAUSE_CHAIN_LENGTH:
            raise ValueError("cause_chain exceeds the maximum length")
        return [sanitize_type_token(entry) for entry in entries]
    if key in ("response_part_types", "tool_names"):
        if value is None:
            return []
        return [sanitize_type_token(entry) for entry in value]
    return value


def open_eval_trace(path: Path | None) -> EvalTraceWriter | None:
    """Open (append) the diagnostic trace and write its header.

    Args:
        path: The explicit operator-supplied trace path, or ``None`` to disable
            tracing entirely.

    Returns:
        An open :class:`EvalTraceWriter`, or ``None`` when disabled.

    Raises:
        EvalTraceError: The parent directory is missing, the target is a
            directory, the file cannot be opened, or the header flush fails.
    """
    if path is None:
        return None

    parent = path.parent
    if not parent.is_dir():
        raise EvalTraceError(f"trace directory does not exist: {parent}")
    if path.is_dir():
        raise EvalTraceError(f"trace path is a directory: {path}")
    try:
        handle = path.open("a", encoding="utf-8", newline="\n")
    except OSError as exc:
        raise EvalTraceError(f"failed to open diagnostic trace: {exc}") from exc

    writer = EvalTraceWriter(path=path, _handle=handle)
    writer.emit(EVENT_TRACE_STARTED, phase=PHASE_PRE_RUN)
    if writer.faulted:
        writer.close()
        raise EvalTraceError("failed to write the diagnostic trace header")
    return writer
