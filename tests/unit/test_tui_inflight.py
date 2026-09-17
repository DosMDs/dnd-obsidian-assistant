"""Cross-capability in-flight gate (TUI-04)."""

from __future__ import annotations

import pytest

from dnd_assistant.tui.inflight import (
    EXCLUSIVE_ASSISTANT,
    EXCLUSIVE_CAMPAIGN_STATE,
    EXCLUSIVE_SESSION,
    InFlightGate,
)


class TestInFlightGate:
    def test_idle_initially(self) -> None:
        gate = InFlightGate()
        assert gate.owner is None
        assert gate.is_busy is False

    def test_single_owner_acquisition(self) -> None:
        gate = InFlightGate()
        assert gate.acquire(EXCLUSIVE_ASSISTANT) is True
        assert gate.owner == EXCLUSIVE_ASSISTANT
        assert gate.acquire(EXCLUSIVE_SESSION) is False
        assert gate.acquire(EXCLUSIVE_CAMPAIGN_STATE) is False
        assert gate.owner == EXCLUSIVE_ASSISTANT

    def test_release_restores_availability(self) -> None:
        gate = InFlightGate()
        gate.acquire(EXCLUSIVE_ASSISTANT)
        gate.release(EXCLUSIVE_ASSISTANT)
        assert gate.owner is None
        assert gate.acquire(EXCLUSIVE_SESSION) is True
        assert gate.owner == EXCLUSIVE_SESSION

    def test_release_by_non_owner_is_ignored(self) -> None:
        gate = InFlightGate()
        gate.acquire(EXCLUSIVE_SESSION)
        gate.release(EXCLUSIVE_ASSISTANT)
        assert gate.owner == EXCLUSIVE_SESSION

    def test_empty_owner_rejected(self) -> None:
        gate = InFlightGate()
        with pytest.raises(ValueError):
            gate.acquire("")
