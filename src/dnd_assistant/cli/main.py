"""CLI entrypoint for D&D Session Assistant.

This module provides the canonical ``dnd`` Typer application.
No application or domain logic lives here — only CLI presentation.
"""

from __future__ import annotations

from pathlib import Path

import typer

from dnd_assistant.cli.ask import _ask_command
from dnd_assistant.cli.bootstrap import bootstrap_app
from dnd_assistant.cli.bootstrap_finalize import register_bootstrap_finalize_command
from dnd_assistant.cli.bootstrap_review import register_bootstrap_review_apply_commands
from dnd_assistant.cli.changeset import changeset_app
from dnd_assistant.cli.eval import eval_app
from dnd_assistant.cli.init import _init_command
from dnd_assistant.cli.post_session import register_session_process_commands
from dnd_assistant.cli.session import _note_command, session_app
from dnd_assistant.cli.time import time_app
from dnd_assistant.cli.vault_path import resolve_vault_root, vault_option
from dnd_assistant.composition.index_rebuild import rebuild_fts_index
from dnd_assistant.config.settings import load_machine_settings, resolve_model_config_path
from dnd_assistant.errors import DndAssistantError, StorageError

app = typer.Typer(
    name="dnd",
    help="D&D Session Assistant — локальный помощник для долговременной памяти кампании.",
)

# ── Session command group ───────────────────────────────────────────────────

register_session_process_commands(session_app)
app.add_typer(session_app)

# ── ChangeSet command group ─────────────────────────────────────────────────

app.add_typer(changeset_app)

# ── Bootstrap command group ─────────────────────────────────────────────────

register_bootstrap_review_apply_commands(bootstrap_app)
register_bootstrap_finalize_command(bootstrap_app)
app.add_typer(bootstrap_app)

# ── Time command group ──────────────────────────────────────────────────────

app.add_typer(time_app)

# ── Eval command group ──────────────────────────────────────────────────────

app.add_typer(eval_app)

# ── Note root command ───────────────────────────────────────────────────────

app.command(name="note")(_note_command)

# ── Ask root command ───────────────────────────────────────────────────────

app.command(name="ask")(_ask_command)

# ── Init root command ──────────────────────────────────────────────────────

app.command(name="init")(_init_command)

# ── TUI command ─────────────────────────────────────────────────────────────


@app.command(name="tui")
def _tui(
    vault: Path | None = vault_option(),  # noqa: B008
    config: Path | None = typer.Option(  # noqa: B008
        None,
        "--config",
        help=(
            "Путь к machine-local TOML файлу конфигурации модели. "
            "Если не указан, используется DND_MODEL_CONFIG_PATH из machine-local настроек."
        ),
        exists=True,
        file_okay=True,
        dir_okay=False,
        readable=True,
        resolve_path=True,
    ),
    profile: str = typer.Option(  # noqa: B008
        ...,
        "--profile",
        help="Имя профиля модели (должен иметь роль AGENT).",
    ),
    allow_write: bool = typer.Option(  # noqa: B008
        False,
        "--allow-write",
        help=(
            "Разрешить запись в Vault для инструментов модели (потолок записи "
            "ассистента). Явные действия с сессией этим флагом не ограничиваются."
        ),
    ),
) -> None:
    """Запустить интерактивный текстовый интерфейс (Textual TUI)."""
    # Deferred import: a normal CLI import must not load the TUI/Textual.
    from dnd_assistant.tui.launcher import run

    try:
        settings = load_machine_settings()
        config_path = resolve_model_config_path(config, settings)
        vault_root = resolve_vault_root(vault, settings)
        run(
            vault_root=vault_root,
            config_path=config_path,
            profile_name=profile,
            allow_agent_write=allow_write,
            deepseek_api_key=settings.deepseek_api_key,
        )
    except DndAssistantError as exc:
        typer.echo(f"Ошибка запуска TUI: {exc}", err=True)
        raise typer.Exit(code=1) from exc


# ── Index command group ─────────────────────────────────────────────────────

index_app = typer.Typer(
    name="index",
    help="Управление производным индексом полнотекстового поиска.",
)
app.add_typer(index_app)


@index_app.command("rebuild")
def _rebuild_index(
    vault: Path | None = vault_option(),  # noqa: B008
) -> None:
    """Перестроить производный индекс FTS из текущих данных Vault."""

    try:
        vault_root = resolve_vault_root(vault)
    except DndAssistantError as exc:
        typer.echo(f"Ошибка: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
    if not audit_log_path.parent.is_dir():
        typer.echo(
            f"Ошибка: директория _system/audit/ не найдена в Vault: {vault_root}",
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        rebuild = rebuild_fts_index(vault_root)
    except StorageError as exc:
        typer.echo(f"Ошибка: не удалось перестроить индекс: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(
        f"Индекс полнотекстового поиска успешно перестроен.\n"
        f"  Сущностей проиндексировано: {rebuild.player_count}\n"
        f"  Путь к индексу: {rebuild.index_path}"
    )


# ── Main app ────────────────────────────────────────────────────────────────


@app.callback()
def _main() -> None:
    """CLI D&D Session Assistant."""
