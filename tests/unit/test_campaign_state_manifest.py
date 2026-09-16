"""S12-01 derived-state manifest DTO tests.

Covers generation identity, artifact-inventory canonicalization, mandatory
non-empty inventory, duplicate detection, logical-path validation and
content-hash validation.  These are pure typed contracts; no filesystem I/O is
performed.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dnd_assistant.domain import DerivedStateArtifact, DerivedStateManifest
from dnd_assistant.domain.types import Sha256Fingerprint

_FINGERPRINT = Sha256Fingerprint(digest="a" * 64)


def _artifact(path: str = "Party.md", digest: str = "b" * 64) -> DerivedStateArtifact:
    return DerivedStateArtifact(
        relative_path=path,
        content_hash=Sha256Fingerprint(digest=digest),
    )


def _manifest(**overrides: object) -> DerivedStateManifest:
    kwargs: dict[str, object] = {
        "render_version": "1",
        "input_fingerprint": _FINGERPRINT,
        "artifacts": (_artifact(),),
    }
    kwargs.update(overrides)
    return DerivedStateManifest(**kwargs)  # type: ignore[arg-type]


class TestManifestConstruction:
    def test_minimal_manifest(self) -> None:
        manifest = _manifest()
        assert manifest.schema_version == 2
        assert manifest.state_schema_version == 2
        assert manifest.render_version == "1"
        assert manifest.input_fingerprint == _FINGERPRINT
        assert manifest.artifacts == (_artifact(),)

    def test_requires_generation_fingerprint(self) -> None:
        with pytest.raises(ValidationError):
            DerivedStateManifest(render_version="1", artifacts=(_artifact(),))  # type: ignore[call-arg]

    def test_requires_render_version(self) -> None:
        with pytest.raises(ValidationError):
            DerivedStateManifest(input_fingerprint=_FINGERPRINT, artifacts=(_artifact(),))  # type: ignore[call-arg]

    @pytest.mark.parametrize("version", [1, 3, "2"])
    def test_only_manifest_schema_version_two_accepted(self, version: object) -> None:
        with pytest.raises(ValidationError):
            DerivedStateManifest.model_validate(
                {**_manifest().model_dump(), "schema_version": version}
            )

    def test_requires_at_least_one_artifact(self) -> None:
        with pytest.raises(ValidationError, match="at least one artifact"):
            _manifest(artifacts=())

    def test_frozen(self) -> None:
        with pytest.raises(ValidationError):
            _manifest().input_fingerprint = _FINGERPRINT  # type: ignore[misc]

    def test_forbids_extra_fields(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            DerivedStateManifest.model_validate({**_manifest().model_dump(), "root": "/vault"})

    def test_inventory_contains_only_supplied_artifacts(self) -> None:
        manifest = _manifest(artifacts=(_artifact("Party.md"), _artifact("World State.md")))
        paths = [a.relative_path for a in manifest.artifacts]
        assert paths == ["Party.md", "World State.md"]
        assert "manifest.json" not in paths


class TestArtifactOrdering:
    def test_duplicate_logical_paths_rejected(self) -> None:
        with pytest.raises(ValidationError, match="duplicate"):
            _manifest(artifacts=(_artifact("Party.md"), _artifact("Party.md")))

    def test_non_sequence_input_is_canonicalized(self) -> None:
        manifest = _manifest(
            artifacts=(
                artifact
                for artifact in (
                    _artifact("World State.md", "1" * 64),
                    _artifact("Party.md", "2" * 64),
                )
            )
        )
        assert [a.relative_path for a in manifest.artifacts] == ["Party.md", "World State.md"]

    def test_empty_set_rejected(self) -> None:
        with pytest.raises(ValidationError, match="at least one artifact"):
            _manifest(artifacts=set())

    def test_ordering_is_canonicalized(self) -> None:
        a = _manifest(
            artifacts=(
                _artifact("World State.md", "1" * 64),
                _artifact("Party.md", "2" * 64),
            )
        )
        b = _manifest(
            artifacts=(
                _artifact("Party.md", "2" * 64),
                _artifact("World State.md", "1" * 64),
            )
        )
        assert a.artifacts == b.artifacts
        assert [x.relative_path for x in a.artifacts] == ["Party.md", "World State.md"]


class TestArtifactValidation:
    @pytest.mark.parametrize(
        "path",
        ["/etc/passwd", "..\\escape.md", "../escape.md", "a/../b.md", "", " lead.md"],
    )
    def test_invalid_logical_paths_rejected(self, path: str) -> None:
        with pytest.raises(ValidationError):
            _artifact(path)

    def test_valid_nested_logical_path(self) -> None:
        assert _artifact("State/World State.md").relative_path == "State/World State.md"

    def test_bad_content_hash_rejected(self) -> None:
        with pytest.raises(ValidationError):
            _artifact(digest="not-a-hash")

    def test_artifact_forbids_extra_fields(self) -> None:
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            DerivedStateArtifact.model_validate(
                {
                    "relative_path": "Party.md",
                    "content_hash": {"algorithm": "sha256", "digest": "b" * 64},
                    "absolute_path": "/vault/State/Party.md",
                }
            )
