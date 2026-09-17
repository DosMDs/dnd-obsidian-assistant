"""Responsive presentation styles for the TUI (TUI-05).

A single Textual-free Python string owned by the presentation layer.  It is
assigned to ``DndTuiApp.CSS`` so it is packaged with the module (no external
``.tcss`` asset and no packaging change) and always loaded by Textual.

Breakpoint classes (``-w-*`` / ``-h-*``) are applied to the active ``Screen`` by
Textual's native ``Screen._on_resize`` from the ascending
``App.HORIZONTAL_BREAKPOINTS`` / ``App.VERTICAL_BREAKPOINTS`` tables.  There is
no custom responsive engine, no layout abstraction and no geometry arithmetic.

Terminal-size contract:

    reference        100x30
    baseline          80x24
    minimum usable    60x20
    below minimum     degraded/scrollable, not claimed fully usable
"""

from __future__ import annotations

__all__ = ["RESPONSIVE_CSS"]

RESPONSIVE_CSS = """
/* Assistant composer editor: fixed height so it renders inside auto-height
   parents (the TextArea default is 1fr, which would collapse). */
#assistant-query {
    height: 6;
}

/* Narrow and below-minimum terminals: stack the action rows so no control is
   horizontally clipped, and shrink the composer. */
Screen.-w-narrow #assistant-actions,
Screen.-w-tiny #assistant-actions,
Screen.-w-narrow #session-actions,
Screen.-w-tiny #session-actions,
Screen.-w-narrow #campaign-state-actions,
Screen.-w-tiny #campaign-state-actions {
    layout: vertical;
    height: auto;
}

Screen.-w-narrow #assistant-actions Button,
Screen.-w-tiny #assistant-actions Button,
Screen.-w-narrow #session-actions Button,
Screen.-w-tiny #session-actions Button,
Screen.-w-narrow #campaign-state-actions Button,
Screen.-w-tiny #campaign-state-actions Button {
    width: 100%;
}

Screen.-w-narrow #assistant-query,
Screen.-w-tiny #assistant-query {
    height: 4;
}
"""
