"""CLI entrypoint for D&D Session Assistant.

This module provides the canonical ``dnd`` Typer application.
No application or domain logic lives here — only CLI presentation.
"""

from __future__ import annotations

import typer

app = typer.Typer(
    name="dnd",
    help="D&D Session Assistant — local, offline-first campaign memory.",
)


@app.callback()
def _main() -> None:
    """D&D Session Assistant CLI."""
