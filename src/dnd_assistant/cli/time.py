"""Deterministic world-time administration CLI (``dnd time init``).

This module owns only CLI presentation and lightweight composition wiring:

- Typer option parsing;
- recovery preflight before mutation;
- invoking ``ObsidianWorldTimeRepository.initialize_current_world_time``;
- Russian success/conflict/error rendering and exit-code mapping.

It is model-free: no LLM profile, prompt or tool is involved.  It accepts only a
raw signed ``WorldTick``, initializes revision 1 exactly once, refuses to
overwrite an existing ``world_time.json`` and never infers or converts a tick.
It does not offer ``set``/``advance``/calendar/natural-language behavior.
"""

from __future__ import annotations

from pathlib import Path

import typer

from dnd_assistant.cli.session import _recovery_preflight
from dnd_assistant.composition.audit_context import build_audit_context
from dnd_assistant.composition.world_time import compose_world_time_repository
from dnd_assistant.errors import ConflictError, DndAssistantError

__all__ = ["time_app"]

_VAULT_HELP = "Путь к корню Obsidian Vault."

time_app = typer.Typer(
    name="time",
    help="Управление каноническим игровым временем.",
)


@time_app.command("init")
def _time_init(
    vault: Path = typer.Option(  # noqa: B008
        ...,
        "--vault",
        help=_VAULT_HELP,
        exists=True,
        file_okay=False,
        dir_okay=True,
        readable=True,
        resolve_path=True,
    ),
    world_tick: int = typer.Option(  # noqa: B008
        ...,
        "--world-tick",
        help="Начальный мировой такт (сырое знаковое целое, минуты от эпохи).",
    ),
) -> None:
    """Инициализировать начальное мировое время (однократно, без модели)."""
    vault_root = vault.resolve(strict=False)
    if not vault_root.is_dir():
        typer.echo(
            f"Ошибка: корень Vault должен быть существующей директорией: {vault_root}",
            err=True,
        )
        raise typer.Exit(code=1)

    try:
        _recovery_preflight(vault_root)
        repository = compose_world_time_repository(vault_root)
        audit = build_audit_context(source="cli", prefix="cli-time-init")
        state = repository.initialize_current_world_time(world_tick, audit=audit)
    except ConflictError as exc:
        typer.echo(
            "Ошибка: world_time.json уже существует; начальное мировое время не изменено.\n"
            f"  Причина: {exc}",
            err=True,
        )
        raise typer.Exit(code=1) from exc
    except DndAssistantError as exc:
        typer.echo(f"Ошибка: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(
        "Мировое время инициализировано.\n"
        f"  Текущий такт: {state.current_world_tick}\n"
        f"  Ревизия: {state.revision}"
    )
