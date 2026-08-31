"""Domain tests for CurrentWorldTime schema.

Tests cover:
- valid construction with negative, zero, and positive ticks
- strict type rejection (bool, str, float)
- revision validation
- extra fields rejected
- wrong type rejected
- immutability
- JSON roundtrip
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from dnd_assistant.domain.world_time import CurrentWorldTime


class TestCurrentWorldTimeConstruction:
    """Valid CurrentWorldTime construction with various tick values."""

    def test_negative_tick(self) -> None:
        state = CurrentWorldTime(current_world_tick=-13800, revision=1)
        assert state.current_world_tick == -13800
        assert state.revision == 1

    def test_zero_tick(self) -> None:
        state = CurrentWorldTime(current_world_tick=0, revision=1)
        assert state.current_world_tick == 0

    def test_positive_tick(self) -> None:
        state = CurrentWorldTime(current_world_tick=13800, revision=5)
        assert state.current_world_tick == 13800
        assert state.revision == 5

    def test_default_schema_version(self) -> None:
        state = CurrentWorldTime(current_world_tick=0, revision=1)
        assert state.schema_version == 1

    def test_default_type(self) -> None:
        state = CurrentWorldTime(current_world_tick=0, revision=1)
        assert state.type == "world_time"


class TestCurrentWorldTimeValidation:
    """Strict type and value rejection."""

    def test_bool_tick_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CurrentWorldTime(current_world_tick=True, revision=1)  # type: ignore[arg-type]

    def test_str_tick_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CurrentWorldTime(current_world_tick="13800", revision=1)  # type: ignore[arg-type]

    def test_float_tick_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CurrentWorldTime(current_world_tick=13800.0, revision=1)  # type: ignore[arg-type]

    def test_revision_zero_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CurrentWorldTime(current_world_tick=0, revision=0)

    def test_revision_bool_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CurrentWorldTime(current_world_tick=0, revision=True)  # type: ignore[arg-type]

    def test_extra_fields_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CurrentWorldTime.model_validate(
                {
                    "schema_version": 1,
                    "type": "world_time",
                    "current_world_tick": 0,
                    "revision": 1,
                    "extra_field": "unexpected",
                }
            )

    def test_wrong_type_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CurrentWorldTime.model_validate(
                {
                    "schema_version": 1,
                    "type": "wrong_type",
                    "current_world_tick": 0,
                    "revision": 1,
                }
            )

    def test_wrong_schema_version_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CurrentWorldTime.model_validate(
                {
                    "schema_version": 99,
                    "type": "world_time",
                    "current_world_tick": 0,
                    "revision": 1,
                }
            )


class TestCurrentWorldTimeImmutability:
    """Frozen model enforcement."""

    def test_cannot_set_tick(self) -> None:
        state = CurrentWorldTime(current_world_tick=0, revision=1)
        with pytest.raises(ValidationError):
            state.current_world_tick = 100  # type: ignore[misc]

    def test_cannot_set_revision(self) -> None:
        state = CurrentWorldTime(current_world_tick=0, revision=1)
        with pytest.raises(ValidationError):
            state.revision = 2  # type: ignore[misc]


class TestCurrentWorldTimeRoundtrip:
    """JSON serialization roundtrip."""

    def test_json_roundtrip(self) -> None:
        original = CurrentWorldTime(current_world_tick=-13800, revision=1)
        data = original.model_dump(mode="json")
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        restored = CurrentWorldTime.model_validate(json.loads(text))
        assert restored == original

    def test_json_roundtrip_positive(self) -> None:
        original = CurrentWorldTime(current_world_tick=999999, revision=42)
        data = original.model_dump(mode="json")
        text = json.dumps(data, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        restored = CurrentWorldTime.model_validate(json.loads(text))
        assert restored == original
