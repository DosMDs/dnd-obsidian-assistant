"""Shared test fixtures.

This module provides reusable fixtures for the test suite.
Fixtures defined here are globally available via pytest discovery
but have zero effect unless explicitly requested by a test module.

Current fixtures:

- ``_isolate_machine_dotenv`` — autouse fixture that keeps the developer's
  machine dotenv from leaking into non-live tests.  Under the CFG-01 default
  discovery the dotenv resolves to the nearest enclosing ``dnd-assistant``
  project root, which in a source checkout is the repository-root ``.env``.
  The fixture points ``DND_ENV_FILE`` at an empty temporary file so the
  dedicated dotenv contributes nothing; tests that need a specific dotenv
  override it explicitly.  Opt-in live tests (``deepseek`` / ``ollama``) are
  excluded because they deliberately read machine configuration.
- ``restore_dnd_assistant_modules`` — opt-in fixture that snapshots
  all ``dnd_assistant`` modules before each test and restores them
  afterward.  Only tests that deliberately delete ``dnd_assistant``
  modules from ``sys.modules`` for clean-import assertions need this.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

_LIVE_MARKERS = ("deepseek", "ollama")


@pytest.fixture(scope="session")
def _isolated_machine_env_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """An empty dedicated dotenv used to neutralize machine config in tests."""
    path = tmp_path_factory.mktemp("machine-env") / "isolated-empty.env"
    path.write_text("", encoding="utf-8")
    return path


@pytest.fixture(autouse=True)
def _isolate_machine_dotenv(
    request: pytest.FixtureRequest,
    monkeypatch: pytest.MonkeyPatch,
    _isolated_machine_env_file: Path,
) -> None:
    """Point ``DND_ENV_FILE`` at an empty file unless the test is live opt-in."""
    if any(request.node.get_closest_marker(marker) for marker in _LIVE_MARKERS):
        return
    from dnd_assistant.config.settings import MACHINE_ENV_FILE_ENV

    monkeypatch.setenv(MACHINE_ENV_FILE_ENV, str(_isolated_machine_env_file))


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
