"""S13-01 integration tests: real temporary filesystem Vault initialization."""

from __future__ import annotations

import concurrent.futures
import hashlib
import subprocess
from pathlib import Path
from typing import cast

import pytest

from dnd_assistant.application.vault_initialization import (
    VaultInitializationResult,
    VaultInitializationService,
    VaultInitializationStatus,
)
from dnd_assistant.composition.audit_context import build_audit_context
from dnd_assistant.composition.vault_initialization import (
    compose_vault_initialization_service,
)
from dnd_assistant.errors import StorageError
from dnd_assistant.storage.audit import AuditContext, AuditService
from dnd_assistant.storage.vault_initialization import (
    CAMPAIGN_CONFIG_RELATIVE,
    MANAGED_DIRECTORIES,
    ObsidianVaultInitializer,
    parse_campaign_config,
)

GOLDEN_VAULT = Path(__file__).resolve().parents[1] / "fixtures" / "golden_test_vault"


# ── Helpers ──────────────────────────────────────────────────────────────────


def _audit() -> AuditContext:
    return build_audit_context(source="test", prefix="test-init")


def _service(root: Path) -> VaultInitializationService:
    return compose_vault_initialization_service(root)


def _snapshot(root: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_file():
            result[path.relative_to(root).as_posix()] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    return result


def _audit_records(root: Path):
    return AuditService(str(root / "_system" / "audit" / "audit.jsonl")).read_all()


def _can_symlink() -> bool:
    import tempfile

    tmp = Path(tempfile.mkdtemp())
    try:
        target = tmp / "target"
        target.mkdir()
        (tmp / "link").symlink_to(target, target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        return False
    finally:
        import shutil

        shutil.rmtree(tmp, ignore_errors=True)


def _make_junction(link: Path, target: Path) -> bool:
    if not hasattr(Path, "is_junction"):  # pragma: no cover - py<3.12
        return False
    try:
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(link), str(target)],
            capture_output=True,
            text=True,
        )
    except (OSError, FileNotFoundError):
        return False
    return result.returncode == 0 and link.is_junction()


requires_symlink = pytest.mark.skipif(not _can_symlink(), reason="host cannot create symlinks")


class _ScriptedAudit:
    """Minimal audit-service double recording calls and failing on demand."""

    def __init__(self, fail_on: set[int] | None = None) -> None:
        self.records: list[object] = []
        self._fail_on = fail_on or set()

    def append(self, record: object) -> None:
        self.records.append(record)
        if len(self.records) in self._fail_on:
            raise StorageError(f"injected audit failure at call {len(self.records)}")


def _service_with_audit(root: Path, audit_obj: object) -> VaultInitializationService:
    initializer = ObsidianVaultInitializer(root, lambda: cast("AuditService", audit_obj))
    return VaultInitializationService(initializer)


# ── Fresh / already-initialized states ───────────────────────────────────────


class TestFreshInitialization:
    def test_empty_directory_created(self, tmp_path: Path) -> None:
        root = tmp_path / "Vault"
        root.mkdir()
        result = _service(root).initialize(audit=_audit())

        assert result.status is VaultInitializationStatus.CREATED
        assert result.campaign_id.startswith("camp_")
        for relative in MANAGED_DIRECTORIES:
            assert (root / relative).is_dir(), relative
        assert (root / CAMPAIGN_CONFIG_RELATIVE).is_file()

    def test_config_contains_only_minimum_core(self, tmp_path: Path) -> None:
        root = tmp_path / "Vault"
        root.mkdir()
        _service(root).initialize(audit=_audit())
        text = (root / CAMPAIGN_CONFIG_RELATIVE).read_text(encoding="utf-8")
        assert "schema_version: 1" in text
        assert "campaign_id:" in text
        assert "campaign_name" not in text
        assert "calendar" not in text
        assert "features" not in text

    def test_audit_intent_and_committed_written_once(self, tmp_path: Path) -> None:
        root = tmp_path / "Vault"
        root.mkdir()
        _service(root).initialize(audit=_audit())
        records = _audit_records(root)
        assert [r.phase for r in records] == ["intent", "committed"]
        assert all(r.operation == "vault.initialize" for r in records)

    def test_no_derived_data_or_world_time_created(self, tmp_path: Path) -> None:
        root = tmp_path / "Vault"
        root.mkdir()
        _service(root).initialize(audit=_audit())
        assert not (root / "_system" / "world_time.json").exists()
        assert not (root / "_system" / "indexes").exists()
        assert not (root / "_system" / "changesets").exists()
        assert not (root / "State").exists()
        assert not list(root.rglob("*.sqlite3"))

    def test_unicode_vault_path(self, tmp_path: Path) -> None:
        root = tmp_path / "Кампания Серый Брод"
        root.mkdir()
        result = _service(root).initialize(audit=_audit())
        assert result.status is VaultInitializationStatus.CREATED
        assert (root / CAMPAIGN_CONFIG_RELATIVE).is_file()


class TestAlreadyInitialized:
    def test_second_init_zero_writes_and_stable_identity(self, tmp_path: Path) -> None:
        root = tmp_path / "Vault"
        root.mkdir()
        first = _service(root).initialize(audit=_audit())
        config = root / CAMPAIGN_CONFIG_RELATIVE
        bytes_before = config.read_bytes()
        mtime_before = config.stat().st_mtime_ns
        snapshot_before = _snapshot(root)
        audit_before = len(_audit_records(root))

        second = _service(root).initialize(audit=_audit())

        assert second.status is VaultInitializationStatus.ALREADY_INITIALIZED
        assert second.campaign_id == first.campaign_id
        assert second.created_directories == ()
        assert second.audit_recorded is False
        assert config.read_bytes() == bytes_before
        assert config.stat().st_mtime_ns == mtime_before
        assert _snapshot(root) == snapshot_before
        assert len(_audit_records(root)) == audit_before

    def test_valid_config_missing_dirs_repaired(self, tmp_path: Path) -> None:
        import shutil

        root = tmp_path / "Vault"
        root.mkdir()
        first = _service(root).initialize(audit=_audit())
        config = root / CAMPAIGN_CONFIG_RELATIVE
        bytes_before = config.read_bytes()
        shutil.rmtree(root / "Locations")
        shutil.rmtree(root / "_system" / "raw" / "sessions")

        result = _service(root).initialize(audit=_audit())

        assert result.status is VaultInitializationStatus.COMPLETED_PARTIAL
        assert result.campaign_id == first.campaign_id
        assert set(result.created_directories) == {"Locations", "_system/raw/sessions"}
        assert (root / "Locations").is_dir()
        assert (root / "_system" / "raw" / "sessions").is_dir()
        assert config.read_bytes() == bytes_before
        assert len(_audit_records(root)) == 4


# ── Preservation / no-scan / containment ─────────────────────────────────────


class TestPreservation:
    def test_ordinary_obsidian_vault_unrelated_bytes_preserved(self, tmp_path: Path) -> None:
        root = tmp_path / "Vault"
        root.mkdir()
        (root / ".obsidian").mkdir()
        (root / ".obsidian" / "app.json").write_text('{"name":"Мой Vault"}', encoding="utf-8")
        (root / "Мои заметки.md").write_text("# Привет\n\nЗаметка.\n", encoding="utf-8")
        (root / "assets").mkdir()
        (root / "assets" / "image.bin").write_bytes(bytes(range(256)))
        before = _snapshot(root)

        _service(root).initialize(audit=_audit())

        after = _snapshot(root)
        for relative, digest in before.items():
            assert after[relative] == digest, relative
        assert (root / ".obsidian" / "app.json").read_text(encoding="utf-8") == (
            '{"name":"Мой Vault"}'
        )

    def test_no_arbitrary_markdown_scan(self, tmp_path: Path) -> None:
        root = tmp_path / "Vault"
        root.mkdir()
        malformed = root / "broken.md"
        malformed.write_text("---\n: : :\nnot: [valid\n---\nbody\n", encoding="utf-8")
        invalid_utf8 = root / "binary.md"
        invalid_utf8.write_bytes(b"\xff\xfe\x00\x01 not utf8")

        result = _service(root).initialize(audit=_audit())

        assert result.status is VaultInitializationStatus.CREATED
        assert malformed.read_text(encoding="utf-8") == "---\n: : :\nnot: [valid\n---\nbody\n"
        assert invalid_utf8.read_bytes() == b"\xff\xfe\x00\x01 not utf8"

    def test_no_write_outside_vault_root(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        (outside / "keep.txt").write_text("keep", encoding="utf-8")
        root = tmp_path / "Vault"
        root.mkdir()

        _service(root).initialize(audit=_audit())

        assert list(outside.iterdir()) == [outside / "keep.txt"]
        assert (outside / "keep.txt").read_text(encoding="utf-8") == "keep"

    def test_golden_vault_copy_recognized_without_rewrite_or_import(self, tmp_path: Path) -> None:
        import shutil

        root = tmp_path / "golden"
        shutil.copytree(GOLDEN_VAULT, root)
        before = _snapshot(root)

        result = _service(root).initialize(audit=_audit())

        assert result.status is VaultInitializationStatus.ALREADY_INITIALIZED
        assert result.campaign_id == "camp_golden_001"
        assert result.audit_recorded is False
        assert _snapshot(root) == before


# ── Conflicts / fail-closed ──────────────────────────────────────────────────


class TestConflicts:
    def test_file_where_directory_expected_fails_before_mutation(self, tmp_path: Path) -> None:
        root = tmp_path / "Vault"
        root.mkdir()
        (root / "Locations").write_text("user file", encoding="utf-8")

        with pytest.raises(StorageError):
            _service(root).initialize(audit=_audit())

        assert not (root / "_system").exists()
        assert not (root / CAMPAIGN_CONFIG_RELATIVE).exists()
        assert (root / "Locations").read_text(encoding="utf-8") == "user file"

    def test_system_dir_as_file_fails_closed(self, tmp_path: Path) -> None:
        root = tmp_path / "Vault"
        root.mkdir()
        (root / "_system").write_text("not a dir", encoding="utf-8")

        with pytest.raises(StorageError):
            _service(root).initialize(audit=_audit())

        assert (root / "_system").read_text(encoding="utf-8") == "not a dir"

    def test_invalid_existing_config_never_overwritten(self, tmp_path: Path) -> None:
        root = tmp_path / "Vault"
        (root / "_system").mkdir(parents=True)
        config = root / CAMPAIGN_CONFIG_RELATIVE
        config.write_text("schema_version: 99\ncampaign_id: x\n", encoding="utf-8")
        before = config.read_bytes()

        with pytest.raises(StorageError):
            _service(root).initialize(audit=_audit())

        assert config.read_bytes() == before
        assert not (root / "Sessions").exists()

    def test_config_directory_rejected(self, tmp_path: Path) -> None:
        root = tmp_path / "Vault"
        (root / "_system" / CAMPAIGN_CONFIG_RELATIVE.name).mkdir(parents=True)
        with pytest.raises(StorageError):
            _service(root).initialize(audit=_audit())


# ── Symlink / junction policy ────────────────────────────────────────────────


class TestPathRedirects:
    @requires_symlink
    def test_managed_symlink_rejected(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        root = tmp_path / "Vault"
        root.mkdir()
        (root / "_system").symlink_to(outside, target_is_directory=True)

        with pytest.raises(StorageError):
            _service(root).initialize(audit=_audit())

        assert list(outside.iterdir()) == []
        assert not (root / CAMPAIGN_CONFIG_RELATIVE).exists()

    @requires_symlink
    def test_dangling_symlink_rejected(self, tmp_path: Path) -> None:
        root = tmp_path / "Vault"
        root.mkdir()
        (root / "_system").symlink_to(tmp_path / "does-not-exist", target_is_directory=True)

        with pytest.raises(StorageError):
            _service(root).initialize(audit=_audit())

        assert not (root / CAMPAIGN_CONFIG_RELATIVE).exists()

    @requires_symlink
    def test_root_symlink_resolved_and_writes_only_into_target(self, tmp_path: Path) -> None:
        real = tmp_path / "real_vault"
        real.mkdir()
        link = tmp_path / "link_vault"
        link.symlink_to(real, target_is_directory=True)

        result = _service(link).initialize(audit=_audit())

        assert result.status is VaultInitializationStatus.CREATED
        assert (real / CAMPAIGN_CONFIG_RELATIVE).is_file()
        assert (real / "Sessions").is_dir()
        # The link name is not a second physical location.
        assert (link / CAMPAIGN_CONFIG_RELATIVE).is_file()

    def test_symlink_branch_fails_closed_deterministic(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import pathlib

        root = tmp_path / "Vault"
        root.mkdir()
        target = root / "_system"
        target.mkdir()

        real_is_symlink = pathlib.Path.is_symlink

        def fake_is_symlink(self: pathlib.Path) -> bool:
            if self == target:
                return True
            return real_is_symlink(self)

        monkeypatch.setattr(pathlib.Path, "is_symlink", fake_is_symlink)

        with pytest.raises(StorageError, match="symlink"):
            _service(root).initialize(audit=_audit())

    def test_junction_branch_fails_closed_deterministic(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import pathlib

        root = tmp_path / "Vault"
        root.mkdir()
        target = root / "_system"
        target.mkdir()

        real_is_junction = pathlib.Path.is_junction

        def fake_is_junction(self: pathlib.Path) -> bool:
            if self == target:
                return True
            return real_is_junction(self)

        monkeypatch.setattr(pathlib.Path, "is_junction", fake_is_junction)

        with pytest.raises(StorageError, match="junction"):
            _service(root).initialize(audit=_audit())

    def test_real_junction_rejected(self, tmp_path: Path) -> None:
        outside = tmp_path / "outside"
        outside.mkdir()
        root = tmp_path / "Vault"
        root.mkdir()
        link = root / "_system"
        if not _make_junction(link, outside):
            pytest.skip("host cannot create a Windows directory junction")
        try:
            with pytest.raises(StorageError):
                _service(root).initialize(audit=_audit())
            assert list(outside.iterdir()) == []
        finally:
            if link.is_junction():
                link.rmdir()


# ── Failure injection / recovery ─────────────────────────────────────────────


class TestFailureInjection:
    def test_directory_creation_failure_safe_rerun(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = tmp_path / "Vault"
        root.mkdir()
        original = ObsidianVaultInitializer._ensure_directory

        def failing(self: ObsidianVaultInitializer, relative: Path) -> bool:
            if relative == Path("Locations"):
                raise StorageError("injected directory failure")
            return original(self, relative)

        monkeypatch.setattr(ObsidianVaultInitializer, "_ensure_directory", failing)
        with pytest.raises(StorageError, match="injected"):
            _service(root).initialize(audit=_audit())

        assert not (root / CAMPAIGN_CONFIG_RELATIVE).exists()
        assert (root / "Sessions").is_dir()

        monkeypatch.undo()
        result = _service(root).initialize(audit=_audit())
        assert result.status is VaultInitializationStatus.CREATED
        assert (root / CAMPAIGN_CONFIG_RELATIVE).is_file()

    def test_audit_intent_failure_blocks_remaining_mutation(self, tmp_path: Path) -> None:
        root = tmp_path / "Vault"
        root.mkdir()
        audit_obj = _ScriptedAudit(fail_on={1})
        with pytest.raises(StorageError):
            _service_with_audit(root, audit_obj).initialize(audit=_audit())

        assert not (root / CAMPAIGN_CONFIG_RELATIVE).exists()
        assert not (root / "Sessions").exists()
        assert not (root / "Locations").exists()

    def test_committed_audit_failure_reports_committed_state(self, tmp_path: Path) -> None:
        root = tmp_path / "Vault"
        root.mkdir()
        audit_obj = _ScriptedAudit(fail_on={2})
        with pytest.raises(StorageError, match="may already be committed"):
            _service_with_audit(root, audit_obj).initialize(audit=_audit())

        assert (root / CAMPAIGN_CONFIG_RELATIVE).is_file()

    def test_unsupported_hardlink_publication_leaves_no_config(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import dnd_assistant.storage.atomic as atomic_mod

        root = tmp_path / "Vault"
        root.mkdir()

        def unsupported(_src: str, _dst: str) -> None:
            raise OSError(95, "operation not supported")

        monkeypatch.setattr(atomic_mod.os, "link", unsupported)
        with pytest.raises(StorageError):
            _service(root).initialize(audit=_audit())

        assert not (root / CAMPAIGN_CONFIG_RELATIVE).exists()


# ── Concurrency ──────────────────────────────────────────────────────────────


class TestConcurrency:
    def test_two_concurrent_inits_one_identity(self, tmp_path: Path) -> None:
        root = tmp_path / "Vault"
        root.mkdir()
        service = _service(root)

        def _run() -> VaultInitializationResult:
            return service.initialize(audit=_audit())

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(_run) for _ in range(2)]
            results = [f.result() for f in futures]

        ids = {r.campaign_id for r in results}
        assert len(ids) == 1
        config_text = (root / CAMPAIGN_CONFIG_RELATIVE).read_text(encoding="utf-8")
        persisted_id = parse_campaign_config(config_text).campaign_id
        assert ids == {persisted_id}

    def test_concurrent_init_exactly_one_config_file(self, tmp_path: Path) -> None:
        root = tmp_path / "Vault"
        root.mkdir()
        service = _service(root)

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _i: service.initialize(audit=_audit()), range(2)))

        configs = list((root / "_system").glob("campaign.yaml"))
        assert len(configs) == 1
        leftovers = [p for p in (root / "_system").iterdir() if p.name.endswith(".tmp")]
        assert leftovers == []
