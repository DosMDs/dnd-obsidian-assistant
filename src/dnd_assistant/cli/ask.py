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
from dnd_assistant.cli.vault_path import resolve_vault_root, vault_option
from dnd_assistant.config.settings import load_machine_settings, resolve_model_config_path
from dnd_assistant.errors import DndAssistantError

# ── Ask command ────────────────────────────────────────────────────────────


def _ask_command(
    query: str = typer.Argument(  # noqa: B008
        ...,
        help="Текст запроса к ассистенту кампании.",
    ),
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
        help="Разрешить запись в Vault через инструменты модели.",
    ),
) -> None:
    """Задать вопрос ассистенту кампании.

    По умолчанию работает в режиме только для чтения.
    Используйте --allow-write для разрешения записи.
    """
    runtime: AskRuntime | None = None

    try:
        # Resolve machine-local settings once: explicit --config wins over
        # DND_MODEL_CONFIG_PATH / machine-local dotenv, and explicit --vault
        # wins over DND_VAULT_PATH.
        settings = load_machine_settings()
        config_path = resolve_model_config_path(config, settings)
        vault_root = resolve_vault_root(vault, settings)

        # Perform recovery preflight inside the error boundary so that
        # project errors from recovery inspection are caught by the CLI
        # DndAssistantError handler.
        _recovery_preflight(vault_root)

        # Compose runtime
        runtime = compose_ask_runtime(
            vault_root=vault_root,
            config_path=config_path,
            profile_name=profile,
            allow_write=allow_write,
            deepseek_api_key=settings.deepseek_api_key,
        )

        # Execute the Pydantic AI agent runtime
        result = runtime.agent_runtime.run(
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
