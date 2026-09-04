"""CLI entrypoint for D&D Session Assistant.

This module provides the canonical ``dnd`` Typer application.
No application or domain logic lives here — only CLI presentation.
"""

from __future__ import annotations

from pathlib import Path

import typer

from dnd_assistant.cli.ask import _ask_command
from dnd_assistant.cli.session import _note_command, session_app
from dnd_assistant.errors import StorageError
from dnd_assistant.retrieval.index import SqliteFtsIndex
from dnd_assistant.storage.audit import AuditService
from dnd_assistant.storage.vault_repository import ObsidianVaultRepository

app = typer.Typer(
    name="dnd",
    help="D&D Session Assistant — локальный помощник для долговременной памяти кампании.",
)

# ── Session command group ───────────────────────────────────────────────────

app.add_typer(session_app)

# ── Note root command ───────────────────────────────────────────────────────

app.command(name="note")(_note_command)

# ── Ask root command ───────────────────────────────────────────────────────

app.command(name="ask")(_ask_command)

# ── Index command group ─────────────────────────────────────────────────────

index_app = typer.Typer(
    name="index",
    help="Управление производным индексом полнотекстового поиска.",
)
app.add_typer(index_app)


@index_app.command("rebuild")
def _rebuild_index(
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
    """Перестроить производный индекс FTS из текущих данных Vault."""

    vault_root = vault.resolve(strict=False)

    # Validate Vault root
    if not vault_root.is_dir():
        typer.echo(
            f"Ошибка: корень Vault должен быть существующей директорией: {vault_root}",
            err=True,
        )
        raise typer.Exit(code=1)

    # Compose read-only Vault access
    try:
        audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        if not audit_log_path.parent.is_dir():
            typer.echo(
                f"Ошибка: директория _system/audit/ не найдена в Vault: {vault_root}",
                err=True,
            )
            raise typer.Exit(code=1)

        audit_service = AuditService(str(audit_log_path))
        repository = ObsidianVaultRepository(
            vault_root=str(vault_root),
            audit_service=audit_service,
        )
    except StorageError as exc:
        typer.echo(f"Ошибка: не удалось открыть Vault: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    # Read all canonical documents
    try:
        documents = repository.list_entities()
    except StorageError as exc:
        typer.echo(f"Ошибка: не удалось прочитать сущности Vault: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    # Rebuild index
    try:
        index = SqliteFtsIndex(vault_root=str(vault_root))
        index.rebuild(documents)
    except StorageError as exc:
        typer.echo(f"Ошибка: не удалось перестроить индекс: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    player_count = sum(1 for d in documents if d.entity.visibility.value == "player")
    typer.echo(
        f"Индекс полнотекстового поиска успешно перестроен.\n"
        f"  Сущностей проиндексировано: {player_count}\n"
        f"  Путь к индексу: {index.index_path}"
    )


# ── Main app ────────────────────────────────────────────────────────────────


@app.callback()
def _main() -> None:
    """CLI D&D Session Assistant."""
