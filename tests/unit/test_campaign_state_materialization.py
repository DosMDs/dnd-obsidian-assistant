"""S12-03 Campaign State materialization unit tests (controlled derivations).

Uses a real ``ObsidianDerivedStateStore`` over a temporary Vault but controls
the source derivation (and therefore the fingerprint/status) directly, so the
publication gate, deterministic re-render verification, coordinated-edit
detection and fail-closed statuses can be exercised without canonical
mutations.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from dnd_assistant.application.campaign_state_materialization import (
    CampaignStateReadError,
    CampaignStateRebuildStatus,
    CampaignStateSourceChangedError,
    CampaignStateStaleError,
    CampaignStateStatus,
    inspect_campaign_state,
    read_current_campaign_state,
    rebuild_campaign_state,
)
from dnd_assistant.application.campaign_state_render import (
    build_manifest,
    render_campaign_state_artifacts,
    serialize_manifest,
)
from dnd_assistant.domain.campaign_state import (
    CampaignState,
    CampaignStateArtifact,
)
from dnd_assistant.errors import NotFoundError, StorageError
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


def _services(tmp_path: Path) -> Services:
    return make_services(make_vault(tmp_path))


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


def _publish_state(store: ObsidianDerivedStateStore, state: CampaignState) -> None:
    texts = render_campaign_state_artifacts(state)
    store.publish(texts, serialize_manifest(build_manifest(state, texts)))


def _rebuild(services: Services, store, *, limit: int = 5):
    return rebuild_campaign_state(
        vault_repository=services.vault,
        session_repository=services.metadata,
        world_time_repository=services.world_time,
        derived_state_store=store,
        recent_session_limit=limit,
    )


def _inspect(services: Services, store, *, limit: int = 5):
    return inspect_campaign_state(
        vault_repository=services.vault,
        session_repository=services.metadata,
        world_time_repository=services.world_time,
        derived_state_store=store,
        recent_session_limit=limit,
    )


def _read(services: Services, store, *, limit: int = 5):
    return read_current_campaign_state(
        vault_repository=services.vault,
        session_repository=services.metadata,
        world_time_repository=services.world_time,
        derived_state_store=store,
        recent_session_limit=limit,
    )


def _patch_build(monkeypatch: pytest.MonkeyPatch, results: list[object]) -> None:
    import dnd_assistant.application.campaign_state_materialization as mod

    iterator = iter(results)

    def fake(**_kwargs: object):
        return next(iterator)

    monkeypatch.setattr(mod, "build_campaign_state", fake)


def _manifest_path(store: ObsidianDerivedStateStore) -> Path:
    return store.state_dir / MANIFEST_FILENAME


def _rewrite_manifest(store: ObsidianDerivedStateStore, mutate) -> None:
    data = json.loads(_manifest_path(store).read_text(encoding="utf-8"))
    mutate(data)
    _manifest_path(store).write_text(json.dumps(data), encoding="utf-8")


# ── Publication gate ──────────────────────────────────────────────────────


class TestPublicationGate:
    def test_pre_publication_mismatch_aborts_with_zero_publication(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        services = _services(tmp_path)
        counting = CountingStore(services.store)
        _patch_build(
            monkeypatch,
            [make_build_result(_FP_A), make_build_result(_FP_B)],
        )
        with pytest.raises(CampaignStateSourceChangedError):
            _rebuild(services, counting)
        assert counting.publish_calls == 0
        assert not services.store.state_dir.exists()

    def test_matching_fingerprint_publishes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        services = _services(tmp_path)
        counting = CountingStore(services.store)
        _patch_build(
            monkeypatch,
            [make_build_result(_FP_A), make_build_result(_FP_A)],
        )
        result = _rebuild(services, counting)
        assert result.status is CampaignStateRebuildStatus.PUBLISHED
        assert counting.publish_calls == 1

    def test_current_rebuild_is_noop(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        services = _services(tmp_path)
        _publish_state(services.store, make_state(_FP_A))
        counting = CountingStore(services.store)
        _patch_build(
            monkeypatch,
            [make_build_result(_FP_A), make_build_result(_FP_A)],
        )
        result = _rebuild(services, counting)
        assert result.status is CampaignStateRebuildStatus.ALREADY_CURRENT
        assert counting.publish_calls == 0


# ── Integrity verification ────────────────────────────────────────────────


class TestIntegrityVerification:
    def test_current_generation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        services = _services(tmp_path)
        _publish_state(services.store, make_state(_FP_A))
        _patch_build(monkeypatch, [make_build_result(_FP_A)])
        inspection = _inspect(services, services.store)
        assert inspection.status is CampaignStateStatus.CURRENT

    def test_coordinated_edit_is_never_current(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        services = _services(tmp_path)
        state = make_state(_FP_A)
        _publish_state(services.store, state)

        # Edit the Markdown and update the manifest hash to match the edited bytes.
        artifact_path = services.store.state_dir / "World State.md"
        edited = b"# World State\n\nTampered.\n"
        artifact_path.write_bytes(edited)
        digest = hashlib.sha256(edited).hexdigest()

        def mutate(data: dict) -> None:
            for entry in data["artifacts"]:
                if entry["relative_path"] == "State/World State.md":
                    entry["content_hash"] = {"algorithm": "sha256", "digest": digest}

        _rewrite_manifest(services.store, mutate)
        _patch_build(monkeypatch, [make_build_result(_FP_A)])

        inspection = _inspect(services, services.store)
        assert inspection.status is CampaignStateStatus.CORRUPT

    def test_both_artifact_coordinated_edit_is_never_current(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        services = _services(tmp_path)
        _publish_state(services.store, make_state(_FP_A))

        # Edit BOTH managed Markdown artifacts and recompute BOTH manifest hashes
        # so the manifest is internally self-consistent with the tampered bytes.
        edited = {
            ARTIFACT_FILENAMES[CampaignStateArtifact.WORLD_STATE]: b"# World State\n\nTampered.\n",
            ARTIFACT_FILENAMES[CampaignStateArtifact.RECENTLY_TOUCHED]: b"# Touched\n\nTampered.\n",
        }
        digest_by_path: dict[str, str] = {}
        for filename, data in edited.items():
            (services.store.state_dir / filename).write_bytes(data)
            digest_by_path[f"State/{filename}"] = hashlib.sha256(data).hexdigest()

        def mutate(data: dict) -> None:
            for entry in data["artifacts"]:
                entry["content_hash"] = {
                    "algorithm": "sha256",
                    "digest": digest_by_path[entry["relative_path"]],
                }

        _rewrite_manifest(services.store, mutate)
        _patch_build(monkeypatch, [make_build_result(_FP_A)])

        # Deterministic re-render comparison catches the coordinated edit even
        # though both stored hashes and the manifest agree.
        assert _inspect(services, services.store).status is CampaignStateStatus.CORRUPT

    def test_edited_bytes_with_unchanged_manifest_hash_is_corrupt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        services = _services(tmp_path)
        _publish_state(services.store, make_state(_FP_A))
        artifact_path = services.store.state_dir / "World State.md"
        artifact_path.write_bytes(b"# Different\n")
        _patch_build(monkeypatch, [make_build_result(_FP_A)])
        assert _inspect(services, services.store).status is CampaignStateStatus.CORRUPT

    def test_artifact_hash_mismatch_is_corrupt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        services = _services(tmp_path)
        _publish_state(services.store, make_state(_FP_A))

        def mutate(data: dict) -> None:
            data["artifacts"][0]["content_hash"] = {"algorithm": "sha256", "digest": "0" * 64}

        _rewrite_manifest(services.store, mutate)
        _patch_build(monkeypatch, [make_build_result(_FP_A)])
        assert _inspect(services, services.store).status is CampaignStateStatus.CORRUPT

    def test_missing_artifact_is_corrupt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        services = _services(tmp_path)
        _publish_state(services.store, make_state(_FP_A))
        (services.store.state_dir / "World State.md").unlink()
        _patch_build(monkeypatch, [make_build_result(_FP_A)])
        assert _inspect(services, services.store).status is CampaignStateStatus.CORRUPT

    def test_artifacts_without_manifest_is_corrupt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        services = _services(tmp_path)
        _publish_state(services.store, make_state(_FP_A))
        _manifest_path(services.store).unlink()
        _patch_build(monkeypatch, [make_build_result(_FP_A)])
        assert _inspect(services, services.store).status is CampaignStateStatus.CORRUPT

    def test_malformed_manifest_is_corrupt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        services = _services(tmp_path)
        _publish_state(services.store, make_state(_FP_A))
        _manifest_path(services.store).write_text("{not json", encoding="utf-8")
        assert _inspect(services, services.store).status is CampaignStateStatus.CORRUPT

    @pytest.mark.parametrize("old_version", ["1", "999"])
    def test_old_or_unknown_render_version_is_outdated(
        self, tmp_path: Path, old_version: str
    ) -> None:
        services = _services(tmp_path)
        _publish_state(services.store, make_state(_FP_A))
        _rewrite_manifest(services.store, lambda d: d.update(render_version=old_version))
        assert _inspect(services, services.store).status is CampaignStateStatus.OUTDATED


# ── Filesystem authority ──────────────────────────────────────────────────


class TestManifestAuthority:
    def _publish_and_rewrite_path(self, store: ObsidianDerivedStateStore, value: str) -> None:
        _publish_state(store, make_state(_FP_A))

        def mutate(data: dict) -> None:
            data["artifacts"][0]["relative_path"] = value

        _rewrite_manifest(store, mutate)

    def test_malicious_drive_form_path_is_corrupt_not_resolved(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        services = _services(tmp_path)
        _patch_build(monkeypatch, [make_build_result(_FP_A)])
        self._publish_and_rewrite_path(services.store, "C:/evil.md")
        inspection = _inspect(services, services.store)
        assert inspection.status is CampaignStateStatus.CORRUPT
        # The manifest path was never used as a physical destination: the State
        # directory still contains exactly the managed files.
        assert {p.name for p in services.store.state_dir.iterdir()} == {
            ARTIFACT_FILENAMES[CampaignStateArtifact.WORLD_STATE],
            ARTIFACT_FILENAMES[CampaignStateArtifact.RECENTLY_TOUCHED],
            MANIFEST_FILENAME,
        }

    def test_traversal_logical_path_is_corrupt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        services = _services(tmp_path)
        _patch_build(monkeypatch, [make_build_result(_FP_A)])
        self._publish_and_rewrite_path(services.store, "../escape.md")
        assert _inspect(services, services.store).status is CampaignStateStatus.CORRUPT


# ── Status / read model ───────────────────────────────────────────────────


class TestStatusAndRead:
    def test_missing(self, tmp_path: Path) -> None:
        services = _services(tmp_path)
        assert _inspect(services, services.store).status is CampaignStateStatus.MISSING
        with pytest.raises(NotFoundError):
            _read(services, services.store)

    def test_stale_and_read_raises(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        services = _services(tmp_path)
        _publish_state(services.store, make_state(_FP_A))
        _patch_build(
            monkeypatch,
            [make_build_result(_FP_B), make_build_result(_FP_B)],
        )
        assert _inspect(services, services.store).status is CampaignStateStatus.STALE
        with pytest.raises(CampaignStateStaleError):
            _read(services, services.store)

    def test_unverifiable_preserves_cause(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import dnd_assistant.application.campaign_state_materialization as mod

        services = _services(tmp_path)
        _publish_state(services.store, make_state(_FP_A))

        def failing(**_kwargs: object):
            raise StorageError("canonical sources unavailable")

        monkeypatch.setattr(mod, "build_campaign_state", failing)

        inspection = _inspect(services, services.store)
        assert inspection.status is CampaignStateStatus.UNVERIFIABLE
        assert isinstance(inspection.cause, StorageError)
        with pytest.raises(CampaignStateReadError) as exc_info:
            _read(services, services.store)
        assert exc_info.value.status is CampaignStateStatus.UNVERIFIABLE
        assert isinstance(exc_info.value.__cause__, StorageError)

    def test_corrupt_read_raises_storage_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        services = _services(tmp_path)
        _publish_state(services.store, make_state(_FP_A))
        _manifest_path(services.store).write_text("{bad", encoding="utf-8")
        with pytest.raises(CampaignStateReadError):
            _read(services, services.store)

    def test_current_read_returns_state(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        services = _services(tmp_path)
        _publish_state(services.store, make_state(_FP_A))
        _patch_build(monkeypatch, [make_build_result(_FP_A)])
        result = _read(services, services.store)
        assert result.state.input_fingerprint.digest == _FP_A
