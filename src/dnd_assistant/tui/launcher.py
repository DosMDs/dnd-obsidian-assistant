"""TUI launch entry point (TUI-03, extended in TUI-04).

Imported lazily by ``dnd_assistant.cli.main``'s ``dnd tui`` command so that a
normal CLI import does not load this package or Textual.
"""

from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr

from dnd_assistant.tui.app import DndTuiApp
from dnd_assistant.tui.services import TuiLaunchContext, build_tui_services

__all__ = ["run"]


def run(
    *,
    vault_root: Path,
    config_path: Path,
    profile_name: str,
    allow_agent_write: bool = False,
    deepseek_api_key: SecretStr | None = None,
) -> None:
    """Run the production TUI with an immutable launch context."""
    launch = TuiLaunchContext(
        vault_root=vault_root,
        config_path=config_path,
        profile_name=profile_name,
        allow_agent_write=allow_agent_write,
        deepseek_api_key=deepseek_api_key,
    )
    DndTuiApp(build_tui_services(launch)).run()
