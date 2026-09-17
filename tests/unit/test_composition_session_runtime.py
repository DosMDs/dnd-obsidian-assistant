"""Unit tests for the shared session runtime / recovery composition (TUI-02).

These tests prove the capability-oriented composition extracted from
``cli/session.py``:

- ``compose_session_runtime`` wires a ``SessionRuntimeService``;
- ``compose_recovery_service`` wires a ``SessionRecoveryService``;
- recovery inspection remains literally read-only.

They use a minimal temporary Vault only and require no Ollama/Vault side
effects.  The audit parent directory ``_system/audit/`` is created explicitly
by the fixture because ``AuditService`` requires its parent to exist.
"""

from __future__ import annotations

from pathlib import Path

from dnd_assistant.application.session_recovery import SessionRecoveryService
from dnd_assistant.application.session_runtime import SessionRuntimeService
from dnd_assistant.composition.session_runtime import (
    compose_recovery_service,
    compose_session_runtime,
)

# ── Fixtures ───────────────────────────────────────────────────────────────

_REQUIRED_VAULT_DIRS: tuple[str, ...] = (
    "Sessions",
    "_system",
    "_system/raw",
    "_system/raw/sessions",
    "_system/audit",
)


def _minimal_vault(tmp_path: Path) -> Path:
    """Create a minimal valid Vault with the required audit parent present."""
    vault_root = tmp_path / "vault"
    for relative in _REQUIRED_VAULT_DIRS:
        (vault_root / relative).mkdir(parents=True, exist_ok=True)
    return vault_root


def _snapshot(root: Path) -> dict[str, bytes | None]:
    """Capture literal filesystem state: relative path -> file bytes (dirs None)."""
    snapshot: dict[str, bytes | None] = {}
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root)).replace("\\", "/")
        snapshot[relative] = None if path.is_dir() else path.read_bytes()
    return snapshot


# ── Session runtime composition ────────────────────────────────────────────


class TestComposeSessionRuntime:
    """Shared session runtime composition capability."""

    def test_returns_wired_session_runtime_service(self, tmp_path: Path) -> None:
        service = compose_session_runtime(_minimal_vault(tmp_path))
        assert isinstance(service, SessionRuntimeService)

    def test_reads_active_session_from_empty_vault(self, tmp_path: Path) -> None:
        service = compose_session_runtime(_minimal_vault(tmp_path))
        assert service.get_active_session() is None


# ── Recovery composition / trusted inspection ──────────────────────────────


class TestComposeRecoveryService:
    """Shared session recovery composition capability."""

    def test_returns_wired_recovery_service(self, tmp_path: Path) -> None:
        service = compose_recovery_service(_minimal_vault(tmp_path))
        assert isinstance(service, SessionRecoveryService)

    def test_partition_is_empty_on_clean_vault(self, tmp_path: Path) -> None:
        partition = compose_recovery_service(_minimal_vault(tmp_path)).inspect_runtime_partition()
        assert partition.blocking == ()
        assert partition.externally_owned == ()

    def test_inspection_is_literally_read_only(self, tmp_path: Path) -> None:
        """Snapshot filesystem bytes before/after inspection and compare."""
        vault_root = _minimal_vault(tmp_path)

        before = _snapshot(vault_root)
        service = compose_recovery_service(vault_root)
        service.inspect_runtime()
        service.inspect_runtime_partition()
        after = _snapshot(vault_root)

        assert after == before
