"""Shared presentation-neutral audit-context factory (TUI-04).

Proves the extracted composition seam keeps CLI provenance unchanged and adds a
distinct TUI provenance, with compatible time/operation-id helpers.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from dnd_assistant.cli.session import (
    _build_audit_context,
    _new_operation_id,
    _now_utc,
)
from dnd_assistant.composition.audit_context import (
    build_audit_context,
    new_operation_id,
    now_utc,
)


class TestSharedAuditFactory:
    def test_tui_source_is_stamped(self) -> None:
        context = build_audit_context(source="tui", prefix="tui-session-start")
        assert context.source == "tui"
        assert context.operation_id.startswith("tui-session-start-")
        assert context.model_profile is None
        assert context.prompt_version is None

    def test_cli_source_is_stamped(self) -> None:
        context = build_audit_context(source="cli", prefix="cli-note")
        assert context.source == "cli"
        assert context.operation_id.startswith("cli-note-")

    def test_operation_ids_are_unique(self) -> None:
        first = new_operation_id("tui-note")
        second = new_operation_id("tui-note")
        assert first != second

    def test_now_utc_is_timezone_aware(self) -> None:
        assert now_utc().tzinfo is not None


class TestCliPreservedBehaviour:
    """The CLI provenance and directly-tested private helpers are unchanged."""

    def test_cli_build_audit_context_source_is_cli(self) -> None:
        context = _build_audit_context("cli", "cli-session-end")
        assert context.source == "cli"
        assert context.operation_id.startswith("cli-session-end-")

    def test_cli_now_utc_returns_aware_datetime(self) -> None:
        value = _now_utc()
        assert isinstance(value, datetime)
        assert value.tzinfo is not None
        assert value.utcoffset() == timedelta(0)

    def test_cli_new_operation_id_has_prefix(self) -> None:
        assert _new_operation_id("cli-test").startswith("cli-test-")
