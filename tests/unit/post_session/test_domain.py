"""S11-01 domain schema and value-type tests."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import TypeAdapter
from pydantic import ValidationError as PydanticValidationError

from dnd_assistant.domain.post_session import (
    ArtifactKind,
    ArtifactPersisted,
    AttemptCompleted,
    AttemptFailed,
    AttemptStarted,
    AttemptSuperseded,
    FailureCategory,
    PostSessionAttemptId,
    ProcessingLedgerEvent,
    ProcessingOutcome,
    ProcessingPhase,
    ProposalPersisted,
    Sha256Fingerprint,
)

_AWARE = datetime(2026, 8, 31, 16, 0, 0, tzinfo=UTC)
_ATT = "att_" + "a" * 32
_EVT = "le_" + "b" * 32
_FP = Sha256Fingerprint(digest="c" * 64)

_LEDGER_ADAPTER: TypeAdapter[ProcessingLedgerEvent] = TypeAdapter(ProcessingLedgerEvent)


def _common() -> dict[str, Any]:
    return {
        "event_id": _EVT,
        "attempt_id": _ATT,
        "session_ref": "S001",
        "real_time": _AWARE,
    }


def test_valid_attempt_id_accepted() -> None:
    assert _LEDGER_ADAPTER.validate_python(
        {
            "event_kind": "attempt_started",
            **_common(),
            "input_fingerprint": _FP.model_dump(mode="json"),
            "processor_version": "1",
            "prompt_version": "1",
        }
    )


@pytest.mark.parametrize(
    "bad",
    [
        "att_" + "A" * 32,
        "att_" + "a" * 31,
        "att_" + "a" * 33,
        "att_../../etc",
        "ATT_" + "a" * 32,
        "att-" + "a" * 32,
        "",
        "att_",
    ],
)
def test_path_unsafe_attempt_id_rejected(bad: str) -> None:
    payload = {
        **{k: v for k, v in _common().items() if k != "attempt_id"},
        "event_kind": "attempt_started",
        "attempt_id": bad,
        "input_fingerprint": _FP.model_dump(mode="json"),
        "processor_version": "1",
        "prompt_version": "1",
    }
    with pytest.raises(PydanticValidationError):
        AttemptStarted.model_validate(payload)


def test_valid_fingerprint_accepted() -> None:
    fp = Sha256Fingerprint(digest="0" * 64)
    assert fp.algorithm == "sha256"
    assert fp.digest == "0" * 64


@pytest.mark.parametrize("bad", ["", "0" * 63, "0" * 65, "C" * 64, "z" * 64])
def test_malformed_fingerprint_rejected(bad: str) -> None:
    with pytest.raises(PydanticValidationError):
        Sha256Fingerprint(digest=bad)


def test_ledger_discriminated_union_parses_every_kind() -> None:
    payloads = [
        {
            "event_kind": "attempt_started",
            **_common(),
            "input_fingerprint": _FP.model_dump(mode="json"),
            "processor_version": "1",
            "prompt_version": "1",
            "model_profile": None,
        },
        {
            "event_kind": "artifact_persisted",
            **_common(),
            "artifact_kind": "summary",
            "relative_path": "attempts/x/summary.md",
            "content_hash": _FP.model_dump(mode="json"),
        },
        {
            "event_kind": "proposal_persisted",
            **_common(),
            "changeset_id": "cs_S001_att_x",
            "changeset_fingerprint": _FP.model_dump(mode="json"),
        },
        {
            "event_kind": "attempt_completed",
            **_common(),
            "outcome": "produced",
        },
        {
            "event_kind": "attempt_failed",
            **_common(),
            "phase": "extraction",
            "failure_category": "model_timeout",
            "message": "timeout",
        },
        {
            "event_kind": "attempt_superseded",
            **_common(),
            "superseded_by_attempt_id": "att_" + "d" * 32,
            "reason": "rerun",
        },
    ]
    parsed = [_LEDGER_ADAPTER.validate_python(p) for p in payloads]
    assert [e.event_kind for e in parsed] == [
        "attempt_started",
        "artifact_persisted",
        "proposal_persisted",
        "attempt_completed",
        "attempt_failed",
        "attempt_superseded",
    ]
    assert isinstance(parsed[3], AttemptCompleted)
    assert parsed[3].outcome is ProcessingOutcome.PRODUCED
    assert isinstance(parsed[4], AttemptFailed)
    assert parsed[4].phase is ProcessingPhase.EXTRACTION
    assert parsed[4].failure_category is FailureCategory.MODEL_TIMEOUT
    assert isinstance(parsed[1], ArtifactPersisted)
    assert parsed[1].artifact_kind is ArtifactKind.SUMMARY
    assert isinstance(parsed[2], ProposalPersisted)
    assert isinstance(parsed[5], AttemptSuperseded)


def test_unsupported_schema_version_fails_closed() -> None:
    with pytest.raises(PydanticValidationError):
        _LEDGER_ADAPTER.validate_python(
            {
                "event_kind": "attempt_completed",
                **_common(),
                "schema_version": 2,
                "outcome": "produced",
            }
        )


def test_unknown_event_kind_fails_closed() -> None:
    with pytest.raises(PydanticValidationError):
        _LEDGER_ADAPTER.validate_python({"event_kind": "not_a_kind", **_common()})


def test_naive_timestamp_rejected() -> None:
    with pytest.raises(PydanticValidationError):
        AttemptCompleted(
            event_id=_EVT,
            attempt_id=_ATT,
            session_ref="S001",
            real_time=datetime(2026, 8, 31, 16, 0, 0),
            outcome=ProcessingOutcome.PRODUCED,
        )


def test_failure_message_rejects_newlines_and_overlong() -> None:
    with pytest.raises(PydanticValidationError):
        AttemptFailed(
            **_common(),
            phase=ProcessingPhase.EXTRACTION,
            failure_category=FailureCategory.INTERNAL_ERROR,
            message="line1\nline2",
        )
    with pytest.raises(PydanticValidationError):
        AttemptFailed(
            **_common(),
            phase=ProcessingPhase.EXTRACTION,
            failure_category=FailureCategory.INTERNAL_ERROR,
            message="x" * 2001,
        )


def test_artifact_relative_path_rejects_traversal_and_absolute() -> None:
    for bad in ("/abs/summary.md", "../summary.md", "a/../b.md", "a\\b.md"):
        with pytest.raises(PydanticValidationError):
            ArtifactPersisted(
                **_common(),
                artifact_kind=ArtifactKind.SUMMARY,
                relative_path=bad,
                content_hash=_FP,
            )


def test_ledger_event_invariant_unknown_field_rejected() -> None:
    payload = {**_common(), "event_kind": "attempt_completed", "outcome": "produced", "x": 1}
    with pytest.raises(PydanticValidationError):
        AttemptCompleted.model_validate(payload)


def test_post_session_attempt_id_type_adapter_roundtrip() -> None:
    adapter: TypeAdapter[str] = TypeAdapter(PostSessionAttemptId)
    assert adapter.validate_python(_ATT) == _ATT
