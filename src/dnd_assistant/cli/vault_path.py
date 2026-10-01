"""Shared CLI Vault-path resolution (CFG-02).

This module owns the single presentation-layer boundary that resolves the Vault
root for every Vault-using CLI/TUI command.  It intentionally contains no
repository, domain or storage logic: it merges the explicit ``--vault`` option
with the machine-local :class:`~dnd_assistant.config.settings.MachineSettings`
value and applies the same directory-existence check that the CLI previously
relied on for explicit (Typer-validated) paths.

Precedence (highest first):

    explicit ``--vault``
        > process environment ``DND_VAULT_PATH``
        > selected machine-local dotenv ``DND_VAULT_PATH``
        > deterministic project error

The machine-local setting is consulted **lazily**: when an explicit ``--vault``
is supplied, no dotenv/project-root discovery happens, so explicit invocations
keep working outside a project checkout.  Callers that already loaded settings
for the model-config path pass the instance in to avoid a second parse.

Only directory existence is checked here (matching the former CLI body check);
Vault layout, campaign structure and repository validity remain owned by the
existing Vault/application/storage boundaries.  ``dnd init`` uses the same
helper: it requires an existing target directory but never an already
initialized Vault.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer

from dnd_assistant.config.settings import (
    MachineSettings,
    load_machine_settings,
    resolve_vault_path,
)
from dnd_assistant.errors import ValidationError

__all__ = ["resolve_vault_root", "vault_option"]

_VAULT_OPTION_HELP = (
    "Путь к корню Obsidian Vault. Если не указан, используется "
    "DND_VAULT_PATH из machine-local настроек."
)


def vault_option(*, require_existing_directory: bool = True) -> Any:
    """Return the canonical optional ``--vault`` Typer option (CFG-02).

    Args:
        require_existing_directory: When ``True`` (all Vault-using commands
            except ``init``), preserve the explicit-path Typer checks
            (exists / directory / readable / resolved).  ``dnd init`` passes
            ``False`` to keep its lenient explicit-path semantics: the shared
            resolver still requires an existing target directory, but a bad
            explicit path stays a project error (exit 1) rather than a Typer
            usage error (exit 2).
    """
    if require_existing_directory:
        return typer.Option(  # noqa: B008
            None,
            "--vault",
            help=_VAULT_OPTION_HELP,
            exists=True,
            file_okay=False,
            dir_okay=True,
            readable=True,
            resolve_path=True,
        )
    return typer.Option(None, "--vault", help=_VAULT_OPTION_HELP)  # noqa: B008


def resolve_vault_root(
    explicit: Path | None,
    settings: MachineSettings | None = None,
) -> Path:
    """Resolve the canonical Vault root for a CLI invocation.

    Args:
        explicit: The explicit ``--vault`` value (``None`` when omitted).
        settings: An already-loaded machine settings instance, when the caller
            needs it for other machine-local settings.  Ignored when ``explicit``
            is provided.  Loaded lazily when needed and ``None``.

    Returns:
        The resolved absolute Vault root directory.

    Raises:
        ValidationError: No Vault path is available from either source, or the
            resolved path is not an existing directory.
    """
    path = explicit
    if path is None:
        resolved_settings = settings if settings is not None else load_machine_settings()
        path = resolve_vault_path(None, resolved_settings)

    root = path.expanduser().resolve(strict=False)
    if not root.is_dir():
        raise ValidationError(f"корень Vault должен быть существующей директорией: {root}")
    return root
