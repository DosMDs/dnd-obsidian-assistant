"""Textual presentation host (TUI-03).

This package is the production Textual front-end. It is a **presentation-only**
peer of ``cli/``: it owns no canonical semantics and no write policy. All
trusted behavior is reached through the shared composition/application boundary
(in later track tasks).

Allowed dependency direction::

    tui (Textual)
            |
    composition / application
            |
    domain / storage / retrieval / tools / models

Forbidden: any trusted lower layer importing this package or Textual, and this
package importing ``dnd_assistant.cli``.

Like ``composition``, this ``__init__`` deliberately imports nothing: importing
the launcher must not eagerly pull in every TUI module.
"""

from __future__ import annotations
