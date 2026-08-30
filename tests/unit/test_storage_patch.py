"""Tests for EntityPatch DTO (S3-06).

Covers:
- Allowed fields accepted
- Multiple fields accepted
- Empty patch rejected
- Unknown/immutable fields rejected
- Explicit None semantics (nullable vs non-nullable)
- Canonical field validation reused
- Frozen behaviour
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError as PydanticValidationError

from dnd_assistant.domain.types import KnowledgeStatus, Visibility
from dnd_assistant.storage.patch import EntityPatch

# ═════════════════════════════════════════════════════════════════════════════
# Allowed fields
# ═════════════════════════════════════════════════════════════════════════════


class TestEntityPatchAllowedFields:
    """Each allowed field is accepted individually."""

    def test_name_accepted(self) -> None:
        patch = EntityPatch(name="Gandalf the White")
        assert patch.name == "Gandalf the White"

    def test_status_accepted(self) -> None:
        patch = EntityPatch(status="retired")
        assert patch.status == "retired"

    def test_visibility_accepted(self) -> None:
        patch = EntityPatch(visibility="dm")
        assert patch.visibility == Visibility.DM

    def test_knowledge_status_accepted(self) -> None:
        patch = EntityPatch(knowledge_status="inferred")
        assert patch.knowledge_status == KnowledgeStatus.INFERRED

    def test_created_session_accepted(self) -> None:
        patch = EntityPatch(created_session="S007")
        assert patch.created_session == "S007"

    def test_last_seen_session_accepted(self) -> None:
        patch = EntityPatch(last_seen_session="S014")
        assert patch.last_seen_session == "S014"

    def test_tags_accepted(self) -> None:
        patch = EntityPatch(tags=["wizard", "istari"])
        assert patch.tags == ["wizard", "istari"]

    def test_multiple_fields_accepted(self) -> None:
        patch = EntityPatch(
            name="Gandalf the White",
            status="active",
            visibility="player",
            knowledge_status="confirmed",
            tags=["wizard"],
        )
        assert patch.name == "Gandalf the White"
        assert patch.status == "active"
        assert patch.tags == ["wizard"]


# ═════════════════════════════════════════════════════════════════════════════
# Empty patch rejection
# ═════════════════════════════════════════════════════════════════════════════


class TestEntityPatchEmpty:
    """Empty patch must be rejected."""

    def test_empty_patch_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="at least one editable field"):
            EntityPatch()

    def test_all_none_rejected(self) -> None:
        """Explicitly setting all fields to None is still empty for non-nullable fields."""
        with pytest.raises(PydanticValidationError):
            EntityPatch(
                name=None,
                status=None,
                visibility=None,
                knowledge_status=None,
                tags=None,
            )


# ═════════════════════════════════════════════════════════════════════════════
# Unknown / immutable fields rejected
# ═════════════════════════════════════════════════════════════════════════════


class TestEntityPatchForbiddenFields:
    """Immutable and unknown fields must be rejected."""

    def test_id_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            EntityPatch(id="new-id", name="test")  # type: ignore[call-arg]

    def test_type_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            EntityPatch(type="quest", name="test")  # type: ignore[call-arg]

    def test_created_at_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            EntityPatch(
                created_at=datetime(2026, 8, 30, tzinfo=UTC),  # type: ignore[call-arg]
                name="test",
            )

    def test_updated_at_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            EntityPatch(
                updated_at=datetime(2026, 8, 30, tzinfo=UTC),  # type: ignore[call-arg]
                name="test",
            )

    def test_revision_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            EntityPatch(revision=5, name="test")  # type: ignore[call-arg]

    def test_body_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            EntityPatch(body="new body", name="test")  # type: ignore[call-arg]

    def test_extra_frontmatter_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            EntityPatch(extra_frontmatter={"key": "val"}, name="test")  # type: ignore[call-arg]

    def test_unknown_field_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            EntityPatch(unknown_field="bad", name="test")  # type: ignore[call-arg]

    def test_schema_version_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            EntityPatch(schema_version=2, name="test")  # type: ignore[call-arg]


# ═════════════════════════════════════════════════════════════════════════════
# Explicit None semantics
# ═════════════════════════════════════════════════════════════════════════════


class TestEntityPatchExplicitNone:
    """Nullable fields accept explicit None; non-nullable fields reject it."""

    def test_created_session_explicit_none_accepted(self) -> None:
        patch = EntityPatch(created_session=None, name="test")
        assert patch.created_session is None
        assert "created_session" in patch.model_fields_set

    def test_last_seen_session_explicit_none_accepted(self) -> None:
        patch = EntityPatch(last_seen_session=None, name="test")
        assert patch.last_seen_session is None
        assert "last_seen_session" in patch.model_fields_set

    def test_name_explicit_none_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="non-nullable"):
            EntityPatch(name=None)

    def test_status_explicit_none_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="non-nullable"):
            EntityPatch(status=None, name="test")

    def test_visibility_explicit_none_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="non-nullable"):
            EntityPatch(visibility=None, name="test")

    def test_knowledge_status_explicit_none_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="non-nullable"):
            EntityPatch(knowledge_status=None, name="test")

    def test_tags_explicit_none_rejected(self) -> None:
        with pytest.raises(PydanticValidationError, match="non-nullable"):
            EntityPatch(tags=None, name="test")


# ═════════════════════════════════════════════════════════════════════════════
# Canonical field validation
# ═════════════════════════════════════════════════════════════════════════════


class TestEntityPatchCanonicalValidation:
    """Canonical domain field validation is reused."""

    def test_name_empty_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            EntityPatch(name="")

    def test_name_whitespace_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            EntityPatch(name="  Gandalf  ")

    def test_name_non_printable_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            EntityPatch(name="Gandalf\x00")

    def test_status_empty_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            EntityPatch(status="")

    def test_tag_empty_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            EntityPatch(tags=[""])

    def test_tag_whitespace_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            EntityPatch(tags=["  wizard  "])

    def test_invalid_visibility_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            EntityPatch(visibility="invalid")

    def test_invalid_knowledge_status_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            EntityPatch(knowledge_status="invalid")

    def test_unicode_accepted(self) -> None:
        patch = EntityPatch(name="Гэндальф Белый")
        assert patch.name == "Гэндальф Белый"


# ═════════════════════════════════════════════════════════════════════════════
# Frozen behaviour
# ═════════════════════════════════════════════════════════════════════════════


class TestEntityPatchFrozen:
    """EntityPatch must be immutable after construction."""

    def test_frozen_immutable(self) -> None:
        patch = EntityPatch(name="Gandalf")
        with pytest.raises(PydanticValidationError):
            patch.name = "Changed"  # type: ignore[misc]

    def test_frozen_tags_immutable(self) -> None:
        patch = EntityPatch(tags=["wizard"])
        with pytest.raises(PydanticValidationError):
            patch.tags = ["rogue"]  # type: ignore[misc]


# ═════════════════════════════════════════════════════════════════════════════
# model_fields_set introspection
# ═════════════════════════════════════════════════════════════════════════════


class TestEntityPatchFieldsSet:
    """model_fields_set must correctly reflect supplied fields."""

    def test_single_field_in_fields_set(self) -> None:
        patch = EntityPatch(name="Gandalf")
        assert patch.model_fields_set == {"name"}

    def test_multiple_fields_in_fields_set(self) -> None:
        patch = EntityPatch(name="Gandalf", status="active")
        assert patch.model_fields_set == {"name", "status"}

    def test_explicit_none_in_fields_set(self) -> None:
        patch = EntityPatch(created_session=None, name="test")
        assert "created_session" in patch.model_fields_set
        assert "name" in patch.model_fields_set
