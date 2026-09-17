"""UI-agnostic shared composition seams (TUI-02).

This package owns concrete dependency construction shared by presentation
surfaces (Typer CLI and the future Textual TUI).  It sits above ``application``
as a peer of ``cli/``.

Allowed dependency direction::

    cli / future tui
            |
    composition
            |
    application / storage / retrieval / tools / models

This ``__init__`` deliberately imports nothing: importing a specific
capability module must not eagerly pull in every other capability (for
example, the session composition must not transitively import model/tool
modules through the agent composition).
"""

from __future__ import annotations
