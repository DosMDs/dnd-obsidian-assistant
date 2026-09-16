"""S11-07 unit tests for the read-only post-session outputs read-model.

Focuses on ledger grouping/order and non-completed structural projection; the
verified/fail-closed COMPLETED behavior is covered end-to-end in
``tests/integration/test_cli_post_session.py``.
"""

from __future__ import annotations

from unittest.mock import MagicMock

from dnd_assistant.application.post_session_attempt_state import AttemptState
from dnd_assistant.application.post_session_ledger import (
    new_ledger_event_id,
    serialize_ledger_event,
)
from dnd_assistant.application.post_session_outputs import (
    build_post_session_outputs,
)
from dnd_assistant.domain.post_session import AttemptStarted, Sha256Fingerprint
from tests.unit.post_session.helpers import BASE_END

_SESSION = "S001"
_ATTEMPT_A = "att_" + "a" * 32
_ATTEMPT_B = "att_" + "b" * 32


class _FakeProcessingStore:
    def __init__(self, text: str | None) -> None:
        self._text = text

    def read_ledger_if_present(self, session_id: str) -> str | None:
        return self._text

    def append_ledger_line(self, session_id: str, content: str) -> None:
        raise AssertionError("read-model must not write")

    def ledger_exists(self, session_id: str) -> bool:
        return self._text is not None


def _started_line(attempt_id: str) -> str:
    event = AttemptStarted(
        event_id=new_ledger_event_id(),
        attempt_id=attempt_id,
        session_ref=_SESSION,
        real_time=BASE_END,
        input_fingerprint=Sha256Fingerprint(digest="0" * 64),
        processor_version="2",
        prompt_version="post-session-extraction-v1",
    )
    return serialize_ledger_event(event) + "\n"


def _build(text: str | None):
    return build_post_session_outputs(
        _FakeProcessingStore(text),  # type: ignore[arg-type]
        MagicMock(),
        MagicMock(),
        _SESSION,
    )


def test_empty_ledger_yields_no_attempts() -> None:
    assert _build(None) == ()
    assert _build("") == ()


def test_started_attempts_preserve_ledger_order() -> None:
    text = _started_line(_ATTEMPT_A) + _started_line(_ATTEMPT_B)
    outputs = _build(text)
    assert [item.attempt_id for item in outputs] == [_ATTEMPT_A, _ATTEMPT_B]
    for item in outputs:
        assert item.state is AttemptState.STARTED
        assert item.verified is False
        assert item.outcome is None


def test_physically_duplicated_identical_line_folds_to_one_attempt() -> None:
    line = _started_line(_ATTEMPT_A)
    outputs = _build(line + line)
    assert [item.attempt_id for item in outputs] == [_ATTEMPT_A]
