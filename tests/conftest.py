"""Shared test fixtures.

This module provides reusable fixtures for the test suite.
Fixtures defined here are globally available via pytest discovery
but have zero effect unless explicitly requested by a test module.

Current fixtures:

- ``restore_dnd_assistant_modules`` — opt-in fixture that snapshots
  all ``dnd_assistant`` modules before each test and restores them
  afterward.  Only tests that deliberately delete ``dnd_assistant``
  modules from ``sys.modules`` for clean-import assertions need this.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture
def restore_dnd_assistant_modules() -> Iterator[None]:
    """Snapshot dnd_assistant modules before test; restore after.

    Only tests that deliberately delete ``dnd_assistant`` modules from
    ``sys.modules`` for clean-import boundary assertions need this
    fixture.  It must be explicitly requested — it is NOT autouse.
    """
    import sys

    original = {
        name: module
        for name, module in sys.modules.items()
        if name == "dnd_assistant" or name.startswith("dnd_assistant.")
    }
    try:
        yield
    finally:
        for name in list(sys.modules):
            if name == "dnd_assistant" or name.startswith("dnd_assistant."):
                del sys.modules[name]
        sys.modules.update(original)
