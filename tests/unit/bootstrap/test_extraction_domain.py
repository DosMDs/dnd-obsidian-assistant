"""S13-03 bootstrap extraction domain contract tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dnd_assistant.domain.bootstrap_extraction import (
    BOOTSTRAP_EXTRACTION_SCHEMA_VERSION,
    BootstrapEntityCandidate,
    BootstrapEntityReference,
    BootstrapExtraction,
)
from dnd_assistant.domain.types import EntityType

_FORBIDDEN = ("entity_id", "revision", "path", "pathlib", "candidate_entity_id")


def test_reference_schema_has_no_canonical_identity_field() -> None:
    fields = set(BootstrapEntityReference.model_fields)
    assert fields == {"reference_id", "text", "entity_type", "source_refs"}


def test_candidate_and_extraction_have_no_canonical_identity_fields() -> None:
    for model in (BootstrapEntityCandidate, BootstrapExtraction):
        for forbidden in _FORBIDDEN:
            assert forbidden not in model.model_fields


def test_json_schema_cannot_represent_canonical_entity_id() -> None:
    schema = BootstrapEntityReference.model_json_schema()
    properties = schema.get("properties", {})
    assert "entity_id" not in properties
    assert "candidate_entity_id" not in properties
    assert "revision" not in properties
    assert "path" not in properties


def test_extra_canonical_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        BootstrapEntityReference(
            reference_id="r1",
            text="Варос",
            entity_type=EntityType.NPC,
            source_refs=("src_" + "a" * 32,),
            candidate_entity_id="npc-1",  # type: ignore[call-arg]
        )


def test_schema_version_is_explicit() -> None:
    assert BOOTSTRAP_EXTRACTION_SCHEMA_VERSION == 1
    extraction = BootstrapExtraction(schema_version=BOOTSTRAP_EXTRACTION_SCHEMA_VERSION)
    assert extraction.candidates == ()
    assert extraction.claims == ()


def test_source_refs_must_be_non_empty() -> None:
    with pytest.raises(ValidationError):
        BootstrapEntityReference(
            reference_id="r1",
            text="Варос",
            entity_type=EntityType.NPC,
            source_refs=(),
        )
