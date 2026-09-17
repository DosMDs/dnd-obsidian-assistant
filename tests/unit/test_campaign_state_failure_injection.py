"""S12-05 Campaign State publication failure injection.

Injects I/O failures at every S12-03 publication phase (before/after each
artifact replacement, before/after the manifest replacement) while modelling
both the stored generation/partial state **and** the current canonical source
epoch.  Verifies the corrected verifier order and the core invariant that no
interrupted or mixed generation is ever falsely ``CURRENT``.

Also covers source-derivation failures before ``publish()`` (zero publication)
and confirms derived maintenance never appends canonical audit.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from dnd_assistant.application.campaign_state_materialization import (
    CampaignStateSourceChangedError,
    CampaignStateStatus,
    inspect_campaign_state,
    rebuild_campaign_state,
)
from dnd_assistant.application.campaign_state_render import (
    build_manifest,
    render_campaign_state_artifacts,
    serialize_manifest,
)
from dnd_assistant.application.campaign_state_source import (
    CampaignStateSourceError,
    CampaignStateSourceReason,
)
from dnd_assistant.domain.campaign_state import (
    CampaignState,
    CampaignStateArtifact,
)
from dnd_assistant.errors import StorageError
from dnd_assistant.storage.derived_state import (
    ARTIFACT_FILENAMES,
    MANIFEST_FILENAME,
    ObsidianDerivedStateStore,
)
from tests.unit.campaign_state.helpers import (
    Services,
    make_build_result,
    make_services,
    make_state,
    make_vault,
)

_FP_A = "a" * 64
_FP_B = "b" * 64
_WORLD = ARTIFACT_FILENAMES[CampaignStateArtifact.WORLD_STATE]
_TOUCHED = ARTIFACT_FILENAMES[CampaignStateArtifact.RECENTLY_TOUCHED]
_LIMIT = 5


class CountingStore:
    """Delegating store that counts publication calls."""

    def __init__(self, inner: ObsidianDerivedStateStore) -> None:
        self._inner = inner
        self.publish_calls = 0

    def read_manifest_text(self) -> str | None:
        return self._inner.read_manifest_text()

    def read_artifact_bytes(self, artifact: CampaignStateArtifact) -> bytes | None:
        return self._inner.read_artifact_bytes(artifact)

    def publish(self, artifacts, manifest_text: str) -> None:
        self.publish_calls += 1
        self._inner.publish(artifacts, manifest_text)


def _services(tmp_path: Path) -> Services:
    return make_services(make_vault(tmp_path))


def _publish_state(store: ObsidianDerivedStateStore, state: CampaignState) -> None:
    texts = render_campaign_state_artifacts(state)
    store.publish(texts, serialize_manifest(build_manifest(state, texts)))


def _patch_build(monkeypatch: pytest.MonkeyPatch, results: list[object]) -> None:
    import dnd_assistant.application.campaign_state_materialization as mod

    iterator = iter(results)

    def fake(**_kwargs: object):
        return next(iterator)

    monkeypatch.setattr(mod, "build_campaign_state", fake)


def _rebuild(services: Services, store):
    return rebuild_campaign_state(
        vault_repository=services.vault,
        session_repository=services.metadata,
        world_time_repository=services.world_time,
        derived_state_store=store,
        recent_session_limit=_LIMIT,
    )


def _inspect(services: Services, store):
    return inspect_campaign_state(
        vault_repository=services.vault,
        session_repository=services.metadata,
        world_time_repository=services.world_time,
        derived_state_store=store,
        recent_session_limit=_LIMIT,
    )


def _fault_before_or_after(
    monkeypatch: pytest.MonkeyPatch,
    filename: str,
    when: str,
) -> None:
    """Inject a StorageError immediately before or after one managed write."""
    import dnd_assistant.storage.derived_state as ds

    original = ds.atomic_write_text

    def hook(target, content, *, validator):
        if Path(target).name == filename:
            if when == "before":
                raise StorageError(f"injected failure before {filename}")
            original(target, content, validator=validator)
            raise StorageError(f"injected failure after {filename}")
        return original(target, content, validator=validator)

    monkeypatch.setattr(ds, "atomic_write_text", hook)


def _fail_manifest_replace(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make the shared atomic ``os.replace`` fail only for the manifest leaf.

    Patches the real ``dnd_assistant.storage.atomic.os.replace`` seam so the
    actual shared ``atomic_write_text`` implementation runs (create temp, write,
    fsync, validate) and only the final atomic swap of the manifest fails.
    """
    import dnd_assistant.storage.atomic as atomic_mod

    original = atomic_mod.os.replace

    def failing_replace(src: str, dst: str) -> None:
        if Path(dst).name == MANIFEST_FILENAME:
            raise OSError(30, "Read-only file system")
        original(src, dst)

    monkeypatch.setattr(atomic_mod.os, "replace", failing_replace)


def _tmp_files(store: ObsidianDerivedStateStore) -> list[Path]:
    if not store.state_dir.is_dir():
        return []
    return [p for p in store.state_dir.iterdir() if p.name.endswith(".tmp")]


def _artifact_bytes(store: ObsidianDerivedStateStore, artifact: CampaignStateArtifact) -> bytes:
    data = store.read_artifact_bytes(artifact)
    assert data is not None
    return data


# ── Publication phase matrix (canonical source changed A -> B) ─────────────


class TestPublicationPhaseMatrixChangedSource:
    """Stored generation A; canonical source epoch B; genuine byte change."""

    @pytest.mark.parametrize(
        ("filename", "when", "expected"),
        (
            (_WORLD, "before", CampaignStateStatus.STALE),
            (_WORLD, "after", CampaignStateStatus.CORRUPT),
            (_TOUCHED, "before", CampaignStateStatus.CORRUPT),
            (_TOUCHED, "after", CampaignStateStatus.CORRUPT),
            (MANIFEST_FILENAME, "before", CampaignStateStatus.CORRUPT),
        ),
    )
    def test_fault_status_and_repair(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        filename: str,
        when: str,
        expected: CampaignStateStatus,
    ) -> None:
        services = _services(tmp_path)
        _publish_state(services.store, make_state(_FP_A, tick=100))
        before = _artifact_bytes(services.store, CampaignStateArtifact.WORLD_STATE)

        changed = make_build_result(_FP_B, tick=999)
        _fault_before_or_after(monkeypatch, filename, when)

        _patch_build(monkeypatch, [changed, changed])
        with pytest.raises(StorageError):
            _rebuild(services, services.store)

        assert _tmp_files(services.store) == []
        # Re-derive/inspect against the changed canonical epoch B.
        _patch_build(monkeypatch, [changed])
        assert _inspect(services, services.store).status is expected

        # A subsequent successful rebuild repairs to CURRENT.
        monkeypatch.undo()
        _patch_build(monkeypatch, [changed, changed])
        _rebuild(services, services.store)
        _patch_build(monkeypatch, [changed])
        assert _inspect(services, services.store).status is CampaignStateStatus.CURRENT
        assert _artifact_bytes(services.store, CampaignStateArtifact.WORLD_STATE) != before

    def test_failure_before_first_artifact_leaves_generation_intact_but_stale(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        services = _services(tmp_path)
        state_a = make_state(_FP_A, tick=100)
        _publish_state(services.store, state_a)
        before = _artifact_bytes(services.store, CampaignStateArtifact.WORLD_STATE)

        changed = make_build_result(_FP_B, tick=999)
        _fault_before_or_after(monkeypatch, _WORLD, "before")
        _patch_build(monkeypatch, [changed, changed])
        with pytest.raises(StorageError):
            _rebuild(services, services.store)

        # Old generation bytes are untouched, but it is STALE against epoch B.
        assert _artifact_bytes(services.store, CampaignStateArtifact.WORLD_STATE) == before

        _patch_build(monkeypatch, [changed])
        assert _inspect(services, services.store).status is CampaignStateStatus.STALE


# ── Hidden-only change: identical PLAYER bytes, changed fingerprint ────────


class TestPublicationPhaseHiddenOnly:
    """Stored A and source B differ only in hidden evidence (same PLAYER bytes)."""

    @pytest.mark.parametrize(
        ("filename", "when"),
        (
            (_WORLD, "before"),
            (_WORLD, "after"),
            (_TOUCHED, "before"),
            (_TOUCHED, "after"),
            (MANIFEST_FILENAME, "before"),
        ),
    )
    def test_hidden_only_fault_is_stale_not_corrupt(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        filename: str,
        when: str,
    ) -> None:
        services = _services(tmp_path)
        _publish_state(services.store, make_state(_FP_A, tick=100))

        hidden = make_build_result(_FP_B, tick=100)  # same tick -> same bytes, new fingerprint
        _fault_before_or_after(monkeypatch, filename, when)
        _patch_build(monkeypatch, [hidden, hidden])
        with pytest.raises(StorageError):
            _rebuild(services, services.store)

        assert _tmp_files(services.store) == []
        _patch_build(monkeypatch, [hidden])
        # PLAYER bytes match the old manifest hashes; only the fingerprint differs.
        assert _inspect(services, services.store).status is CampaignStateStatus.STALE

        monkeypatch.undo()
        _patch_build(monkeypatch, [hidden, hidden])
        _rebuild(services, services.store)
        _patch_build(monkeypatch, [hidden])
        assert _inspect(services, services.store).status is CampaignStateStatus.CURRENT


# ── Post-commit manifest uncertainty ───────────────────────────────────────


class TestPostCommitManifest:
    def test_failure_after_manifest_replace_is_committed_current(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        services = _services(tmp_path)
        _publish_state(services.store, make_state(_FP_A, tick=100))

        changed = make_build_result(_FP_B, tick=999)
        _fault_before_or_after(monkeypatch, MANIFEST_FILENAME, "after")
        _patch_build(monkeypatch, [changed, changed])
        # The call reports failure, but the generation was fully committed.
        with pytest.raises(StorageError):
            _rebuild(services, services.store)

        _patch_build(monkeypatch, [changed])
        assert _inspect(services, services.store).status is CampaignStateStatus.CURRENT

    def test_failure_after_manifest_replace_hidden_only_is_committed_current(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        services = _services(tmp_path)
        _publish_state(services.store, make_state(_FP_A, tick=100))

        hidden = make_build_result(_FP_B, tick=100)
        _fault_before_or_after(monkeypatch, MANIFEST_FILENAME, "after")
        _patch_build(monkeypatch, [hidden, hidden])
        with pytest.raises(StorageError):
            _rebuild(services, services.store)

        _patch_build(monkeypatch, [hidden])
        assert _inspect(services, services.store).status is CampaignStateStatus.CURRENT


class TestManifestReplaceFailure:
    def test_manifest_os_replace_failure_never_false_current(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        services = _services(tmp_path)
        _publish_state(services.store, make_state(_FP_A, tick=100))
        before_manifest = services.store.read_manifest_text()
        assert before_manifest is not None

        _fail_manifest_replace(monkeypatch)

        changed = make_build_result(_FP_B, tick=999)
        _patch_build(monkeypatch, [changed, changed])
        with pytest.raises(StorageError):
            _rebuild(services, services.store)

        # The failed atomic swap cleans its temp file and leaves the previous
        # manifest bytes untouched.
        assert _tmp_files(services.store) == []
        assert services.store.read_manifest_text() == before_manifest

        # Artifacts B were published before the manifest swap failed, so the
        # observed mixed generation (artifacts B + manifest A) must never be
        # CURRENT against fresh source witness B.
        _patch_build(monkeypatch, [changed])
        status = _inspect(services, services.store).status
        assert status is CampaignStateStatus.CORRUPT
        assert status is not CampaignStateStatus.CURRENT


# ── Source-derivation failures: zero publication ───────────────────────────


class TestSourceFailureZeroPublication:
    def _seed(self, tmp_path: Path) -> tuple[Services, CountingStore, bytes]:
        services = _services(tmp_path)
        _publish_state(services.store, make_state(_FP_A, tick=100))
        before = _artifact_bytes(services.store, CampaignStateArtifact.WORLD_STATE)
        return services, CountingStore(services.store), before

    def test_initial_source_error_zero_publication(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        services, counting, before = self._seed(tmp_path)

        def failing(**_kwargs: object):
            raise CampaignStateSourceError(CampaignStateSourceReason.INVALID_TOUCHED_ENTITIES, "x")

        import dnd_assistant.application.campaign_state_materialization as mod

        monkeypatch.setattr(mod, "build_campaign_state", failing)
        with pytest.raises(CampaignStateSourceError):
            _rebuild(services, counting)

        assert counting.publish_calls == 0
        assert _artifact_bytes(services.store, CampaignStateArtifact.WORLD_STATE) == before

    def test_initial_storage_error_zero_publication(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        services, counting, before = self._seed(tmp_path)

        def failing(**_kwargs: object):
            raise StorageError("canonical read failed")

        import dnd_assistant.application.campaign_state_materialization as mod

        monkeypatch.setattr(mod, "build_campaign_state", failing)
        with pytest.raises(StorageError):
            _rebuild(services, counting)

        assert counting.publish_calls == 0
        assert _artifact_bytes(services.store, CampaignStateArtifact.WORLD_STATE) == before

    @pytest.mark.parametrize("failure", ["source", "storage"])
    def test_fresh_prepublication_failure_zero_publication(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
    ) -> None:
        services, counting, before = self._seed(tmp_path)
        candidate = make_build_result(_FP_B, tick=999)

        import dnd_assistant.application.campaign_state_materialization as mod

        calls = {"n": 0}

        def fake(**_kwargs: object):
            calls["n"] += 1
            if calls["n"] == 1:
                return candidate
            if failure == "source":
                raise CampaignStateSourceError(
                    CampaignStateSourceReason.INPUT_TOO_LARGE, "too large"
                )
            raise StorageError("fresh canonical read failed")

        monkeypatch.setattr(mod, "build_campaign_state", fake)
        with pytest.raises((CampaignStateSourceError, StorageError)):
            _rebuild(services, counting)

        assert counting.publish_calls == 0
        assert _artifact_bytes(services.store, CampaignStateArtifact.WORLD_STATE) == before

    def test_prepublication_fingerprint_mismatch_zero_publication(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        services, counting, before = self._seed(tmp_path)
        _patch_build(
            monkeypatch,
            [make_build_result(_FP_A, tick=100), make_build_result(_FP_B, tick=999)],
        )
        with pytest.raises(CampaignStateSourceChangedError):
            _rebuild(services, counting)
        assert counting.publish_calls == 0
        assert _artifact_bytes(services.store, CampaignStateArtifact.WORLD_STATE) == before


# ── Audit: derived maintenance never appends canonical audit ───────────────


class TestNoCanonicalAudit:
    def test_partial_failure_and_repair_append_no_audit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        services = _services(tmp_path)
        _publish_state(services.store, make_state(_FP_A, tick=100))
        audit_before = services.audit.read_all()

        changed = make_build_result(_FP_B, tick=999)
        _fault_before_or_after(monkeypatch, _TOUCHED, "before")
        _patch_build(monkeypatch, [changed, changed])
        with pytest.raises(StorageError):
            _rebuild(services, services.store)
        assert services.audit.read_all() == audit_before

        monkeypatch.undo()
        _patch_build(monkeypatch, [changed, changed])
        _rebuild(services, services.store)
        assert services.audit.read_all() == audit_before

    def test_manifest_rewrite_helper_uses_json(self, tmp_path: Path) -> None:
        # Sanity guard for the internal manifest artifact shape used above.
        services = _services(tmp_path)
        _publish_state(services.store, make_state(_FP_A, tick=100))
        raw = (services.store.state_dir / MANIFEST_FILENAME).read_text(encoding="utf-8")
        assert json.loads(raw)["input_fingerprint"]["digest"] == _FP_A
        assert hashlib.sha256(raw.encode("utf-8")).hexdigest()
