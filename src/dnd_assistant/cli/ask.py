"""CLI ``dnd ask`` command — Fast Agent query interface.

This module owns only:

- Typer command declaration
- CLI options
- invoking the composed runtime
- rendering ``outcome.message``
- CLI error mapping

It does NOT own:

- dependency composition (``agent_runtime.py``)
- domain logic
- tool execution
- model invocation
"""

from __future__ import annotations

from pathlib import Path

import typer

from dnd_assistant.cli.agent_runtime import AskRuntime, compose_ask_runtime
from dnd_assistant.cli.session import _recovery_preflight
from dnd_assistant.errors import DndAssistantError

# ── Ask command ────────────────────────────────────────────────────────────


def _ask_command(
    query: str = typer.Argument(  # noqa: B008
        ...,
        help="Текст запроса к ассистенту кампании.",
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
    config: Path = typer.Option(  # noqa: B008
        ...,
        "--config",
        help="Путь к machine-local TOML файлу конфигурации модели.",
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
        help="Разрешить запись в Vault через инструменты модели.",
    ),
) -> None:
    """Задать вопрос ассистенту кампании.

    По умолчанию работает в режиме только для чтения.
    Используйте --allow-write для разрешения записи.
    """
    vault_root = vault.resolve(strict=False)

    # Validate Vault root
    if not vault_root.is_dir():
        typer.echo(
            f"Ошибка: корень Vault должен быть существующей директорией: {vault_root}",
            err=True,
        )
        raise typer.Exit(code=1)

    runtime: AskRuntime | None = None

    try:
        # Perform recovery preflight inside the error boundary so that
        # project errors from recovery inspection are caught by the CLI
        # DndAssistantError handler.
        _recovery_preflight(vault_root)

        # Compose runtime
        runtime = compose_ask_runtime(
            vault_root=vault_root,
            config_path=config,
            profile_name=profile,
            allow_write=allow_write,
        )

        # Execute AgentLoop
        result = runtime.agent_loop.run(
            query,
            execution_context=runtime.execution_context,
        )

        # Render outcome
        typer.echo(result.outcome.message)

    except DndAssistantError as exc:
        typer.echo(f"Ошибка: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    finally:
        if runtime is not None:
            runtime.close()
