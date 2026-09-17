"""S12-05 deterministic concurrency, reader-race and replay hardening.

The accepted Stage-12 design deliberately has no publication lock.  This module
tests the consequence with deterministic interleavings (re-entrant write hooks,
no timing/sleep) rather than assuming safety.  Every assertion is coupled to an
explicit fresh canonical-source witness, so an old coherent snapshot is not
mistaken for CURRENT after the canonical source changed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dnd_assistant.application.campaign_state_materialization import (
    CampaignStateStatus,
    inspect_campaign_state,
)
from dnd_assistant.application.campaign_state_render import (
    build_manifest,
    render_campaign_state_artifacts,
    serialize_manifest,
)
from dnd_assistant.domain.campaign_state import CampaignStateArtifact
from dnd_assistant.storage.derived_state import (
    ARTIFACT_FILENAMES,
    ObsidianDerivedStateStore,
)
from tests.unit.campaign_state.helpers import (
    make_build_result,
    make_reference,
    make_services,
    make_state,
    make_vault,
)

_FP_A = "a" * 64
_FP_B = "b" * 64
_WORLD = CampaignStateArtifact.WORLD_STATE
_TOUCHED = CampaignStateArtifact.RECENTLY_TOUCHED


def _generation(
    fp: str, tick: int, *, name: str | None = None
) -> tuple[dict[CampaignStateArtifact, str], str]:
    references = (make_reference("npc-a", name=name),) if name is not None else ()
    state = make_state(fp, tick=tick, references=references)
    texts = render_campaign_state_artifacts(state)
    return texts, serialize_manifest(build_manifest(state, texts))


def _publish(store: ObsidianDerivedStateStore, fp: str, tick: int) -> None:
    texts, manifest = _generation(fp, tick)
    store.publish(texts, manifest)


def _patch_witness(monkeypatch: pytest.MonkeyPatch, fp: str, tick: int) -> None:
    import dnd_assistant.application.campaign_state_materialization as mod

    monkeypatch.setattr(
        mod, "build_campaign_state", lambda **_kwargs: make_build_result(fp, tick=tick)
    )


def _inspect(store: ObsidianDerivedStateStore):
    services = make_services(store.vault_root)
    return inspect_campaign_state(
        vault_repository=services.vault,
        session_repository=services.metadata,
        world_time_repository=services.world_time,
        derived_state_store=store,
        recent_session_limit=5,
    )


# ── Deterministic writer interleavings ─────────────────────────────────────


class TestWriterInterleavings:
    def test_interleave_after_artifact1_never_false_current(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import dnd_assistant.storage.derived_state as ds

        store = ObsidianDerivedStateStore(make_vault(tmp_path))
        texts_a, man_a = _generation(_FP_A, 100)
        texts_b, man_b = _generation(_FP_B, 999, name="Брен")
        fired = {"done": False}
        real = ds.atomic_write_text

        def hook(target, content, *, validator):
            result = real(target, content, validator=validator)
            if Path(target).name == ARTIFACT_FILENAMES[_WORLD] and not fired["done"]:
                fired["done"] = True
                store.publish(texts_b, man_b)  # writer B runs to completion nested
            return result

        monkeypatch.setattr(ds, "atomic_write_text", hook)
        store.publish(texts_a, man_a)  # writer A continues afterwards
        monkeypatch.undo()

        # Final on-disk state is mixed (World State=B, Recently Touched=A, manifest=A).
        _patch_witness(monkeypatch, _FP_A, 100)
        assert _inspect(store).status is CampaignStateStatus.CORRUPT
        _patch_witness(monkeypatch, _FP_B, 999)
        assert _inspect(store).status is CampaignStateStatus.CORRUPT

    def test_interleave_after_artifact2_never_false_current(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import dnd_assistant.storage.derived_state as ds

        store = ObsidianDerivedStateStore(make_vault(tmp_path))
        texts_a, man_a = _generation(_FP_A, 100)
        texts_b, man_b = _generation(_FP_B, 999, name="Брен")
        fired = {"done": False}
        real = ds.atomic_write_text

        def hook(target, content, *, validator):
            result = real(target, content, validator=validator)
            if Path(target).name == ARTIFACT_FILENAMES[_TOUCHED] and not fired["done"]:
                fired["done"] = True
                store.publish(texts_b, man_b)
            return result

        monkeypatch.setattr(ds, "atomic_write_text", hook)
        store.publish(texts_a, man_a)
        monkeypatch.undo()

        # manifest ends as A's while Recently Touched was overwritten by B.
        _patch_witness(monkeypatch, _FP_A, 100)
        assert _inspect(store).status is CampaignStateStatus.CORRUPT

    def test_coherent_fully_published_generation_is_current(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = ObsidianDerivedStateStore(make_vault(tmp_path))
        _publish(store, _FP_B, 999)
        _patch_witness(monkeypatch, _FP_B, 999)
        assert _inspect(store).status is CampaignStateStatus.CURRENT

    def test_coherent_old_generation_is_stale_against_new_source(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = ObsidianDerivedStateStore(make_vault(tmp_path))
        _publish(store, _FP_A, 100)
        _patch_witness(monkeypatch, _FP_B, 999)
        assert _inspect(store).status is CampaignStateStatus.STALE


# ── Reader / publication race ──────────────────────────────────────────────


class _RacingStore:
    """Delegating store that publishes once at a chosen read step."""

    def __init__(
        self,
        inner: ObsidianDerivedStateStore,
        *,
        trigger: str,
        texts: dict[CampaignStateArtifact, str],
        manifest: str,
    ) -> None:
        self._inner = inner
        self._trigger = trigger
        self._texts = texts
        self._manifest = manifest
        self._fired = False

    def _maybe_fire(self, step: str) -> None:
        if not self._fired and step == self._trigger:
            self._fired = True
            self._inner.publish(self._texts, self._manifest)

    def read_manifest_text(self) -> str | None:
        text = self._inner.read_manifest_text()
        self._maybe_fire("manifest")
        return text

    def read_artifact_bytes(self, artifact: CampaignStateArtifact) -> bytes | None:
        data = self._inner.read_artifact_bytes(artifact)
        if artifact is _WORLD:
            self._maybe_fire("world")
        elif artifact is _TOUCHED:
            self._maybe_fire("touched")
        return data

    def publish(self, artifacts, manifest_text: str) -> None:
        self._inner.publish(artifacts, manifest_text)


class TestReaderPublicationRace:
    def test_manifest_old_artifacts_new_is_corrupt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        inner = ObsidianDerivedStateStore(make_vault(tmp_path))
        _publish(inner, _FP_A, 100)
        texts_b, man_b = _generation(_FP_B, 999, name="Брен")

        racing = _RacingStore(inner, trigger="manifest", texts=texts_b, manifest=man_b)
        services = make_services(inner.vault_root)
        _patch_witness(monkeypatch, _FP_B, 999)
        inspection = inspect_campaign_state(
            vault_repository=services.vault,
            session_repository=services.metadata,
            world_time_repository=services.world_time,
            derived_state_store=racing,
            recent_session_limit=5,
        )
        assert inspection.status is CampaignStateStatus.CORRUPT

    def test_coherent_old_snapshot_is_stale_against_new_source(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        inner = ObsidianDerivedStateStore(make_vault(tmp_path))
        _publish(inner, _FP_A, 100)
        texts_b, man_b = _generation(_FP_B, 999, name="Брен")

        # Publication happens only after both artifacts were read: the observed
        # snapshot was coherent A, but the fresh canonical source is B.
        racing = _RacingStore(inner, trigger="touched", texts=texts_b, manifest=man_b)
        services = make_services(inner.vault_root)
        _patch_witness(monkeypatch, _FP_B, 999)
        inspection = inspect_campaign_state(
            vault_repository=services.vault,
            session_repository=services.metadata,
            world_time_repository=services.world_time,
            derived_state_store=racing,
            recent_session_limit=5,
        )
        assert inspection.status is CampaignStateStatus.STALE

    def test_coherent_old_snapshot_is_current_when_source_unchanged(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        inner = ObsidianDerivedStateStore(make_vault(tmp_path))
        _publish(inner, _FP_A, 100)
        texts_b, man_b = _generation(_FP_B, 999, name="Брен")

        racing = _RacingStore(inner, trigger="touched", texts=texts_b, manifest=man_b)
        services = make_services(inner.vault_root)
        _patch_witness(monkeypatch, _FP_A, 100)
        inspection = inspect_campaign_state(
            vault_repository=services.vault,
            session_repository=services.metadata,
            world_time_repository=services.world_time,
            derived_state_store=racing,
            recent_session_limit=5,
        )
        # CURRENT is verification of the observed coherent A snapshot against an
        # unchanged A witness; it is not a lease on the post-read disk state.
        assert inspection.status is CampaignStateStatus.CURRENT
        # The racing publication did occur.
        assert inner.read_artifact_bytes(_WORLD) == texts_b[_WORLD].encode("utf-8")


# ── Cross-generation replay ────────────────────────────────────────────────


class TestCrossGenerationReplay:
    @pytest.mark.parametrize("manifest_source", ["a", "b"])
    def test_one_artifact_a_one_b_never_current(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, manifest_source: str
    ) -> None:
        store = ObsidianDerivedStateStore(make_vault(tmp_path))
        texts_a, man_a = _generation(_FP_A, 100)
        texts_b, man_b = _generation(_FP_B, 999, name="Брен")
        manifest = man_a if manifest_source == "a" else man_b
        mixed = {_WORLD: texts_a[_WORLD], _TOUCHED: texts_b[_TOUCHED]}
        store.state_dir.mkdir()
        store.publish(mixed, manifest)

        for fp, tick in ((_FP_A, 100), (_FP_B, 999)):
            _patch_witness(monkeypatch, fp, tick)
            assert _inspect(store).status is not CampaignStateStatus.CURRENT

    def test_artifacts_a_manifest_b_is_corrupt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = ObsidianDerivedStateStore(make_vault(tmp_path))
        texts_a, _ = _generation(_FP_A, 100)
        _, man_b = _generation(_FP_B, 999)
        store.state_dir.mkdir()
        store.publish(texts_a, man_b)

        _patch_witness(monkeypatch, _FP_B, 999)
        assert _inspect(store).status is CampaignStateStatus.CORRUPT

    def test_artifacts_b_manifest_a_is_corrupt(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = ObsidianDerivedStateStore(make_vault(tmp_path))
        texts_b, _ = _generation(_FP_B, 999)
        _, man_a = _generation(_FP_A, 100)
        store.state_dir.mkdir()
        store.publish(texts_b, man_a)

        _patch_witness(monkeypatch, _FP_A, 100)
        assert _inspect(store).status is CampaignStateStatus.CORRUPT

    def test_replay_control_coherent_generation_is_current(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        store = ObsidianDerivedStateStore(make_vault(tmp_path))
        _publish(store, _FP_A, 100)
        _publish(store, _FP_B, 999)
        _patch_witness(monkeypatch, _FP_B, 999)
        assert _inspect(store).status is CampaignStateStatus.CURRENT
