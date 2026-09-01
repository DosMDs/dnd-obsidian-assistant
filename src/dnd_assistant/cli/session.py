"""CLI session commands — session start/status/end and note.

This module owns the ``session`` Typer subgroup and the ``note`` root command.
No application or domain logic lives here — only CLI presentation and
runtime composition.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import typer

from dnd_assistant.application.session_recovery import SessionRecoveryService
from dnd_assistant.application.session_runtime import SessionRuntimeService
from dnd_assistant.errors import DndAssistantError
from dnd_assistant.storage.audit import AuditContext, AuditService
from dnd_assistant.storage.session_events import ObsidianSessionEventRepository
from dnd_assistant.storage.session_metadata import ObsidianSessionMetadataRepository
from dnd_assistant.storage.session_recovery import ObsidianSessionRecoveryRepository
from dnd_assistant.storage.world_time import ObsidianWorldTimeRepository

# ── Time and ID helpers (testable via monkeypatch) ─────────────────────────


def _now_utc() -> datetime:
    """Return the current UTC time with timezone awareness."""
    return datetime.now(UTC)


def _new_operation_id(prefix: str) -> str:
    """Return a unique operation ID with a readable prefix."""
    return f"{prefix}-{uuid4().hex}"


# ── AuditContext factory ──────────────────────────────────────────────────


def _build_audit_context(source: str, prefix: str) -> AuditContext:
    """Build a fresh AuditContext for a CLI invocation.

    Args:
        source: The audit source value (e.g. ``"cli"``).
        prefix: The operation-ID prefix (e.g. ``"cli-session-start"``).

    Returns:
        A new ``AuditContext`` with current time, unique operation ID,
        and no model/prompt metadata.
    """
    return AuditContext(
        operation_id=_new_operation_id(prefix),
        real_time=_now_utc(),
        source=source,
        model_profile=None,
        prompt_version=None,
    )


# ── Runtime composition ───────────────────────────────────────────────────


def _compose_runtime(vault_root: Path) -> SessionRuntimeService:
    """Compose a fully wired ``SessionRuntimeService`` for a Vault root.

    Args:
        vault_root: The resolved Vault root path.

    Returns:
        A ready-to-use ``SessionRuntimeService``.
    """
    audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
    audit_service = AuditService(str(audit_log_path))

    session_repo = ObsidianSessionMetadataRepository(vault_root, audit_service)
    event_repo = ObsidianSessionEventRepository(vault_root, audit_service)
    world_time_repo = ObsidianWorldTimeRepository(vault_root, audit_service)

    return SessionRuntimeService(session_repo, world_time_repo, event_repo)


def _compose_recovery(vault_root: Path) -> SessionRecoveryService:
    """Compose a ``SessionRecoveryService`` for recovery preflight.

    Args:
        vault_root: The resolved Vault root path.

    Returns:
        A ready-to-use ``SessionRecoveryService``.
    """
    audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
    audit_service = AuditService(str(audit_log_path))

    recovery_repo = ObsidianSessionRecoveryRepository(vault_root, audit_service)
    return SessionRecoveryService(recovery_repo)


# ── Recovery preflight ────────────────────────────────────────────────────


def _recovery_preflight(vault_root: Path) -> None:
    """Perform a read-only recovery preflight before a mutating operation.

    If recovery issues are found, prints a Russian error message and exits
    non-zero without performing any repair.

    Args:
        vault_root: The resolved Vault root path.

    Raises:
        typer.Exit: If recovery issues exist.
    """
    recovery_service = _compose_recovery(vault_root)
    report = recovery_service.inspect_runtime()

    if report.has_issues:
        lines: list[str] = [
            "Обнаружено повреждённое или незавершённое состояние сессии.",
            "Требуется явное восстановление перед продолжением.",
            "",
            "Обнаруженные проблемы:",
        ]
        for issue in report.issues:
            parts = [f"  [{issue.code}]"]
            if issue.session_id:
                parts.append(f"сессия={issue.session_id}")
            if issue.operation_id:
                parts.append(f"операция={issue.operation_id}")
            if issue.detail:
                parts.append(f"— {issue.detail}")
            lines.append(" ".join(parts))

        typer.echo("\n".join(lines), err=True)
        raise typer.Exit(code=1)


# ── Session Typer subgroup ────────────────────────────────────────────────

session_app = typer.Typer(
    name="session",
    help="Управление игровыми сессиями.",
)


@session_app.command("start")
def _session_start(
    vault: Path = typer.Option(  # noqa: B008
        ...,
        "--vault",
        help="Путь к корню Obsidian Vault.",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
    ),
) -> None:
    """Начать новую игровую сессию."""
    vault_root = vault.resolve(strict=False)

    try:
        _recovery_preflight(vault_root)

        audit = _build_audit_context("cli", "cli-session-start")
        runtime = _compose_runtime(vault_root)
        session = runtime.start_session(audit=audit)

        typer.echo(
            f"Сессия {session.id} начата.\n"
            f"  Статус: {session.status}\n"
            f"  Начало (реальное): {session.real_started_at.isoformat()}\n"
            f"  Начальный такт: {session.world_tick_start}"
        )
    except DndAssistantError as exc:
        typer.echo(f"Ошибка: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@session_app.command("status")
def _session_status(
    vault: Path = typer.Option(  # noqa: B008
        ...,
        "--vault",
        help="Путь к корню Obsidian Vault.",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
    ),
) -> None:
    """Показать статус текущей активной сессии."""
    vault_root = vault.resolve(strict=False)

    try:
        _recovery_preflight(vault_root)

        runtime = _compose_runtime(vault_root)
        session = runtime.get_active_session()

        if session is None:
            typer.echo("Активной сессии нет.")
            raise typer.Exit(code=0)

        typer.echo(
            f"Сессия {session.id}\n"
            f"  Статус: {session.status}\n"
            f"  Начало (реальное): {session.real_started_at.isoformat()}\n"
            f"  Начальный такт: {session.world_tick_start}\n"
            f"  Ревизия: {session.revision}"
        )
    except DndAssistantError as exc:
        typer.echo(f"Ошибка: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@session_app.command("end")
def _session_end(
    vault: Path = typer.Option(  # noqa: B008
        ...,
        "--vault",
        help="Путь к корню Obsidian Vault.",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
    ),
    touched_id: list[str] = typer.Option(  # noqa: B008
        [],
        "--touched-id",
        help="Стабильный ID сущности, затронутой в сессии (можно повторять).",
    ),
) -> None:
    """Завершить текущую активную сессию."""
    vault_root = vault.resolve(strict=False)

    try:
        _recovery_preflight(vault_root)

        audit = _build_audit_context("cli", "cli-session-end")
        runtime = _compose_runtime(vault_root)
        session = runtime.end_session(
            touched_entity_ids=touched_id,
            audit=audit,
        )

        touch_count = len(touched_id)
        touch_line = f"  Затронуто сущностей: {touch_count}" if touch_count else ""

        typer.echo(
            f"Сессия {session.id} завершена.\n"
            f"  Статус: {session.status}\n"
            f"  Окончание (реальное): {session.real_finished_at.isoformat()}\n"
            f"  Конечный такт: {session.world_tick_end}\n"
            f"  Ревизия: {session.revision}" + (f"\n{touch_line}" if touch_line else "")
        )
    except DndAssistantError as exc:
        typer.echo(f"Ошибка: {exc}", err=True)
        raise typer.Exit(code=1) from exc


# ── Note command (root level) ─────────────────────────────────────────────


def _note_command(
    text: str = typer.Argument(  # noqa: B008
        ...,
        help="Текст заметки.",
    ),
    vault: Path = typer.Option(  # noqa: B008
        ...,
        "--vault",
        help="Путь к корню Obsidian Vault.",
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
    ),
) -> None:
    """Добавить заметку в текущую активную сессию."""
    vault_root = vault.resolve(strict=False)

    try:
        _recovery_preflight(vault_root)

        audit = _build_audit_context("cli", "cli-note")
        runtime = _compose_runtime(vault_root)
        event = runtime.record_note(text, audit=audit)

        safe_summary = text[:80] + ("…" if len(text) > 80 else "")
        typer.echo(
            f"Заметка {event.event_id} сохранена.\n"
            f"  Тип: {event.type}\n"
            f"  Такт: {event.world_tick}\n"
            f"  Текст: {safe_summary}"
        )
    except DndAssistantError as exc:
        typer.echo(f"Ошибка: {exc}", err=True)
        raise typer.Exit(code=1) from exc
