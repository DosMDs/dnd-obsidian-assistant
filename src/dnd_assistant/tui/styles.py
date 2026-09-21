"""Responsive presentation styles for the TUI (TUI-05; redesign TUI-UX-01).

A single Textual-free Python string owned by the presentation layer.  It is
assigned to ``DndTuiApp.CSS`` so it is packaged with the module (no external
``.tcss`` asset and no packaging change) and always loaded by Textual.

Layout:

    Header
    main-body (1fr):  assistant workspace (1fr) | campaign sidebar (fixed)
    Footer

The composer lives at the bottom of the assistant workspace and does not extend
underneath the sidebar.

Breakpoint classes (``-w-*`` / ``-h-*``) are applied to the active ``Screen`` by
Textual's native ``Screen._on_resize`` from the ascending
``App.HORIZONTAL_BREAKPOINTS`` / ``App.VERTICAL_BREAKPOINTS`` tables.  There is
no custom responsive engine, no layout abstraction and no geometry arithmetic.

Terminal-size contract:

    reference        100x30
    baseline          80x24
    minimum usable    60x20
    below minimum     degraded/scrollable, not claimed fully usable

Sidebar policy: visible and fixed-width at baseline/reference, compact at
narrow (60-79), hidden below the minimum (``-w-tiny``) where the layout is
degraded and full usability is not claimed.
"""

from __future__ import annotations

__all__ = ["RESPONSIVE_CSS"]

RESPONSIVE_CSS = """
/* Screen degrades safely below the minimum usable size by scrolling. */
Screen {
    overflow-y: auto;
}

/* ── Main workspace body ─────────────────────────────────────────────── */

#main-body {
    height: 1fr;
}

#assistant-view {
    width: 1fr;
    height: 1fr;
    layout: vertical;
    border: round $primary;
    padding: 0 1;
}

#assistant-transcript {
    height: 1fr;
    border: round $panel;
    padding: 0 1;
}

#assistant-composer {
    height: auto;
    layout: vertical;
    border-top: solid $panel;
    padding-top: 1;
}

#assistant-query {
    height: 5;
}

#assistant-status {
    height: auto;
    color: $text-muted;
}

#assistant-actions {
    height: auto;
    align-horizontal: right;
}

/* ── Campaign sidebar ─────────────────────────────────────────────────── */

#campaign-sidebar {
    width: 34;
    height: 1fr;
    layout: vertical;
    overflow-y: auto;
    border: round $panel;
    padding: 0 1;
}

#sidebar-title {
    text-style: bold;
    height: auto;
}

#sidebar-profile {
    height: auto;
    color: $text-muted;
}

#sidebar-section-session {
    text-style: bold;
    height: auto;
    margin-top: 1;
}

#sidebar-session-status {
    height: auto;
}

#sidebar-open-session {
    height: auto;
    margin-top: 1;
}

#campaign-state-view {
    height: auto;
    layout: vertical;
    margin-top: 1;
}

#campaign-state-body {
    height: auto;
}

#campaign-state-actions {
    height: auto;
}

/* ── Secondary session screen ─────────────────────────────────────────── */

#session-view {
    width: 1fr;
    height: 1fr;
    layout: vertical;
    border: round $primary;
    padding: 0 1;
}

/* ── Narrow and below-minimum terminals ───────────────────────────────── */

Screen.-w-baseline #campaign-sidebar {
    width: 30;
}

Screen.-w-narrow #campaign-sidebar {
    width: 24;
}

Screen.-w-tiny #campaign-sidebar {
    display: none;
}

Screen.-w-narrow #assistant-query,
Screen.-w-tiny #assistant-query {
    height: 3;
}

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
"""
