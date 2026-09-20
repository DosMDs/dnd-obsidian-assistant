"""Strict fixed-shape decoding for provider-neutral eval reports.

This module is the public decoder entry point.  It dispatches on
``report_schema_version``:

    schema v2   frozen legacy shape (no failure diagnostics)
    schema v3   current shape (bounded per-sample failure diagnostics)

Both fixed shapes are strict: missing or unexpected keys are rejected at every
DTO boundary.  Open payloads (tool-call ``arguments``) are copied verbatim.
Runtime metadata is open in key names but must literally be ``str -> str``.
Integer fields reject ``bool`` everywhere.  Standard library + this package
only (no Pydantic AI import here); concrete failure classification lives in
``dnd_assistant.composition``.
"""

from __future__ import annotations

import json

from dnd_assistant.evals.report import EvalReport
from dnd_assistant.evals.report_json_decode_shared import (
    decode_identity,
    decode_report,
    require_keys,
    require_mapping,
)
from dnd_assistant.evals.report_json_decode_v2 import decode_full_turn_v2
from dnd_assistant.evals.report_json_decode_v3 import decode_full_turn_v3

SUPPORTED_SCHEMA_VERSIONS = frozenset({2, 3})
"""Every report schema version this decoder accepts."""


def report_from_json(text: str) -> EvalReport:
    """Parse and strictly validate a report JSON document.

    Accepts the frozen schema v2 and the current schema v3.  A v2 document is
    decoded with explicit not-available failure diagnostics.

    Raises:
        ValueError: On malformed JSON, unsupported schema version, missing or
            unexpected keys, or wrong primitive types.
    """
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"report JSON is malformed: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("report JSON root must be an object")

    require_keys(
        data,
        {
            "identity",
            "runtime",
            "sample_contract",
            "decision_observations",
            "full_turn_observations",
            "metrics",
            "sample_scores",
            "latency",
            "safety",
            "quality",
            "run_validity",
            "accepted",
            "reasons",
        },
        "report",
    )

    identity = decode_identity(
        require_mapping(data, "identity", "report"),
        allowed_versions=SUPPORTED_SCHEMA_VERSIONS,
    )
    full_turn_decoder = (
        decode_full_turn_v2 if identity.report_schema_version == 2 else decode_full_turn_v3
    )
    return decode_report(data, identity=identity, full_turn_decoder=full_turn_decoder)
