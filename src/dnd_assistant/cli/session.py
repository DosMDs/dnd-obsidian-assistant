"""CLI session commands — session start/status/end and note.

This module owns the ``session`` Typer subgroup and the ``note`` root command.
No application or domain logic lives here — only CLI presentation. Concrete
dependency construction is delegated to
``dnd_assistant.composition.session_runtime``; this module keeps only Russian
rendering, CLI ``AuditContext`` identity and ``typer`` exit mapping.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import typer

from dnd_assistant.composition.audit_context import (
    build_audit_context,
    new_operation_id,
    now_utc,
)
from dnd_assistant.composition.session_runtime import (
    compose_recovery_service,
    compose_session_runtime,
)
from dnd_assistant.errors import DndAssistantError
from dnd_assistant.storage.audit import AuditContext

# ── AuditContext factory ──────────────────────────────────────────────────
# Time/operation-id construction is shared with the Textual TUI through
# ``dnd_assistant.composition.audit_context``.  The thin ``_now_utc`` /
# ``_new_operation_id`` wrappers preserve the CLI helper names used by tests;
# CLI provenance stays ``source="cli"``.


def _now_utc() -> datetime:
    """Return the current UTC time with timezone awareness."""
    return now_utc()


def _new_operation_id(prefix: str) -> str:
    """Return a unique operation ID with a readable prefix."""
    return new_operation_id(prefix)


def _build_audit_context(source: str, prefix: str) -> AuditContext:
    """Build a fresh AuditContext for a CLI invocation.

    Args:
        source: The audit source value (e.g. ``"cli"``).
        prefix: The operation-ID prefix (e.g. ``"cli-session-start"``).

    Returns:
        A new ``AuditContext`` with current time, unique operation ID,
        and no model/prompt metadata.
    """
    return build_audit_context(source=source, prefix=prefix)


# ── Recovery preflight (CLI presentation) ─────────────────────────────────
# Concrete session/recovery composition is owned by
# ``dnd_assistant.composition.session_runtime``; this CLI layer only maps the
# trusted partition to Russian output and process exit codes.


def _recovery_preflight(vault_root: Path) -> None:
    """Perform a read-only recovery preflight before a mutating operation.

    If blocking recovery issues are found, prints a Russian error message and
    exits non-zero without performing any repair.  Conclusively ChangeSet-owned
    intent-only issues are reported as a non-fatal hint (diagnosis stays in
    ``dnd changeset status``) and do not block unrelated mutations.

    Args:
        vault_root: The resolved Vault root path.

    Raises:
        typer.Exit: If blocking recovery issues exist.
    """
    recovery_service = compose_recovery_service(vault_root)
    partition = recovery_service.inspect_runtime_partition()

    if partition.blocking:
        lines: list[str] = [
            "Обнаружено повреждённое или незавершённое состояние сессии.",
            "Требуется явное восстановление перед продолжением.",
            "",
            "Обнаруженные проблемы:",
        ]
        for issue in partition.blocking:
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

    if partition.externally_owned:
        typer.echo(
            "Примечание: обнаружены незавершённые операции ChangeSet; "
            "они не блокируют изменения. Проверьте `dnd changeset status`:\n"
            + "\n".join(f"  операция={issue.operation_id}" for issue in partition.externally_owned),
            err=True,
        )


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
        runtime = compose_session_runtime(vault_root)
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

        runtime = compose_session_runtime(vault_root)
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
        runtime = compose_session_runtime(vault_root)
        session = runtime.end_session(
            touched_entity_ids=touched_id,
            audit=audit,
        )

        # close_session always stamps the finish timestamp; narrow for the
        # Optional Session field so the CLI can render it.
        assert session.real_finished_at is not None

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
        runtime = compose_session_runtime(vault_root)
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
