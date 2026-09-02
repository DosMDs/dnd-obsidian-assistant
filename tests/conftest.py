"""Root-level test configuration.

The autouse fixture below ensures that ``dnd_assistant`` module identity is
preserved across the entire test suite.  Without it, boundary tests that
temporarily remove and re-import ``dnd_assistant`` modules from
``sys.modules`` would permanently replace module/class objects, causing
false-negative ``isinstance()`` failures in later tests that still hold
references to the original classes.
"""

from __future__ import annotations

import sys
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _restore_dnd_assistant_modules() -> Iterator[None]:
    """Snapshot dnd_assistant modules before each test; restore after.

    Boundary tests use ``_clean_import`` to temporarily remove all
    ``dnd_assistant`` modules from ``sys.modules`` for a clean import
    assertion.  Without restoration, the permanently replaced module
    objects cause false-negative ``isinstance()`` failures in later
    tests from other modules that still hold references to the original
    classes.

    This fixture ensures every test sees the original pre-test module
    graph, regardless of which other tests ran before it.
    """
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
