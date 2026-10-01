"""CLI ``dnd init`` command — deterministic Vault initialization.

This module owns only CLI presentation: argument intake, Russian rendering
and ``typer`` exit mapping.  It contains no filesystem mutation, no path
policy and no initialization state machine; concrete composition is
delegated to ``dnd_assistant.composition.vault_initialization`` and the
trusted policy lives in ``dnd_assistant.application.vault_initialization``.
"""

from __future__ import annotations

from pathlib import Path

import typer

from dnd_assistant.application.vault_initialization import (
    VaultInitializationResult,
    VaultInitializationStatus,
)
from dnd_assistant.cli.vault_path import resolve_vault_root, vault_option
from dnd_assistant.composition.audit_context import build_audit_context
from dnd_assistant.composition.vault_initialization import (
    compose_vault_initialization_service,
)
from dnd_assistant.errors import DndAssistantError


def _render_result(result: VaultInitializationResult) -> str:
    """Render a typed initialization result as Russian CLI text."""
    if result.status is VaultInitializationStatus.CREATED:
        lines = [
            "Vault инициализирован.",
            f"  Кампания: {result.campaign_id}",
            f"  Конфигурация: {result.config_relative_path}",
        ]
        if result.created_directories:
            lines.append(f"  Создано каталогов: {len(result.created_directories)}")
        return "\n".join(lines)

    if result.status is VaultInitializationStatus.COMPLETED_PARTIAL:
        lines = [
            "Инициализация завершена (дозаполнена структура).",
            f"  Кампания: {result.campaign_id}",
        ]
        if result.created_directories:
            lines.append(f"  Создано каталогов: {len(result.created_directories)}")
        return "\n".join(lines)

    return "\n".join(
        [
            "Vault уже инициализирован.",
            f"  Кампания: {result.campaign_id}",
        ]
    )


def _init_command(
    vault: Path | None = vault_option(require_existing_directory=False),  # noqa: B008
) -> None:
    """Инициализировать структуру D&D Session Assistant в выбранном Obsidian Vault."""
    try:
        # ``dnd init`` only requires an existing target directory; it must not
        # require an already initialized Vault.  The shared helper preserves the
        # previous directory check (and its Russian error) for both explicit and
        # machine-local paths.
        vault_root = resolve_vault_root(vault)
        service = compose_vault_initialization_service(vault_root)
        audit = build_audit_context(source="cli", prefix="cli-init")
        result = service.initialize(audit=audit)
    except DndAssistantError as exc:
        typer.echo(f"Ошибка: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(_render_result(result))
