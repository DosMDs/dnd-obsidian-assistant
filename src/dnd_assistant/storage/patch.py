"""EntityPatch DTO for typed partial entity updates.

EntityPatch represents a caller-supplied set of editable Entity fields
for use with ``VaultRepository.patch_entity()``.

Editable fields
---------------

- ``name``
- ``status``
- ``visibility``
- ``knowledge_status``
- ``created_session`` (nullable — explicit ``None`` clears the field)
- ``last_seen_session`` (nullable — explicit ``None`` clears the field)
- ``tags``

Immutable fields (never patchable through this DTO)
----------------------------------------------------

- ``schema_version``
- ``id``
- ``type``
- ``created_at``
- ``updated_at``
- ``revision``
- ``body``
- ``extra_frontmatter``

Omitted vs explicit ``None``
-----------------------------

- Omitted fields are left unchanged on the stored entity.
- Explicit ``None`` for nullable fields (``created_session``,
  ``last_seen_session``) means "clear this field".
- Explicit ``None`` for non-nullable fields (``name``, ``status``,
  ``visibility``, ``knowledge_status``, ``tags``) is rejected.
"""

from __future__ import annotations

from pydantic import BaseModel, model_validator

from dnd_assistant.domain.entity import NameStr, SessionRef, StatusStr, TagStr
from dnd_assistant.domain.types import KnowledgeStatus, Visibility


class EntityPatch(BaseModel):
    """Typed partial update DTO for common Entity fields.

    Only caller-editable fields are accepted.  Unknown fields, immutable
    Entity fields, and ``body``/``extra_frontmatter`` are rejected.

    At least one editable field must be supplied.
    """

    name: NameStr | None = None
    """Human-readable display name (non-nullable, must be supplied if present)."""

    status: StatusStr | None = None
    """Entity lifecycle status (non-nullable, must be supplied if present)."""

    visibility: Visibility | None = None
    """Which actor can see this entity's information (non-nullable)."""

    knowledge_status: KnowledgeStatus | None = None
    """Epistemic state (non-nullable)."""

    created_session: SessionRef = None
    """Session in which this entity was first observed (nullable — explicit
    ``None`` clears the field)."""

    last_seen_session: SessionRef = None
    """Most recent session in which this entity was observed (nullable —
    explicit ``None`` clears the field)."""

    tags: list[TagStr] | None = None
    """Arbitrary string tags (non-nullable, must be supplied if present)."""

    # ── Pydantic configuration ─────────────────────────────────────────

    model_config = {
        "extra": "forbid",
        "frozen": True,
    }

    # ── Model-level validation ──────────────────────────────────────────

    @model_validator(mode="after")
    def _require_at_least_one_field(self) -> EntityPatch:
        """Reject an empty patch (no fields supplied)."""
        if not self.model_fields_set:
            raise ValueError("EntityPatch must include at least one editable field")
        return self

    @model_validator(mode="after")
    def _reject_explicit_none_for_non_nullable(self) -> EntityPatch:
        """Reject explicit ``None`` for non-nullable fields.

        Non-nullable fields: name, status, visibility, knowledge_status, tags.
        """
        non_nullable = {"name", "status", "visibility", "knowledge_status", "tags"}
        for field_name in non_nullable:
            if field_name in self.model_fields_set and getattr(self, field_name) is None:
                raise ValueError(f"Field {field_name!r} is non-nullable and cannot be set to None")
        return self
