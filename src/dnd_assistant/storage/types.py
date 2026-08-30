"""Storage-level types for Vault persistence.

This module defines the persistence representation of campaign entities
as they exist in the Obsidian Vault.  These types are distinct from the
domain Entity model to allow:

- preservation of Markdown body text;
- preservation of unknown/non-core YAML frontmatter fields;
- future type-specific YAML fields without silently deleting them;
- separation of validation concerns (domain) from serialisation concerns (storage).

Domain Entity validation (``extra="forbid"``) is not weakened.  Unknown
frontmatter keys are carried in ``VaultDocument.extra_frontmatter`` and
validated only at the storage layer.

This module belongs to the storage layer and must not import from:
    models, retrieval, tools, application, cli, ollama
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from dnd_assistant.domain.types import EntityType

if TYPE_CHECKING:
    from dnd_assistant.domain.entity import Entity
    from dnd_assistant.domain.types import EntityId, Revision


# ── Entity directory mapping ───────────────────────────────────────────────


class EntityDirectory(StrEnum):
    """Vault subdirectory for each MVP EntityType.

    Maps the canonical entity type to the Obsidian Vault directory
    where its Markdown files are stored.
    """

    NPC = "Characters/NPCs"
    LOCATION = "Locations"
    QUEST = "Quests"
    ITEM = "Items"

    @classmethod
    def for_type(cls, entity_type: EntityType) -> EntityDirectory:
        """Return the directory for a given EntityType.

        Raises KeyError for entity types not yet mapped in the MVP.
        """
        mapping: dict[EntityType, EntityDirectory] = {
            EntityType.NPC: cls.NPC,
            EntityType.LOCATION: cls.LOCATION,
            EntityType.QUEST: cls.QUEST,
            EntityType.ITEM: cls.ITEM,
        }
        return mapping[entity_type]


# ── VaultDocument ──────────────────────────────────────────────────────────


class VaultDocument:
    """Storage-level representation of a persisted entity document.

    A VaultDocument wraps:
    - a validated domain ``Entity`` (canonical fields);
    - a ``dict`` of extra YAML frontmatter keys not covered by the
      domain Entity schema;
    - the raw Markdown body text following the frontmatter block.

    This separation ensures that domain validation (``extra="forbid"``)
    is never weakened for persistence convenience.  Extra frontmatter
    keys and their values are preserved semantically (key/value pairs)
    during read/write cycles.  YAML presentation metadata (comments,
    scalar style/quoting, anchors, key ordering) is not guaranteed to
    be preserved; that decision is deferred to S3-01.
    """

    def __init__(
        self,
        entity: Entity,
        extra_frontmatter: Mapping[str, object] | None = None,
        body: str = "",
    ) -> None:
        self._entity = entity
        self._extra_frontmatter = dict(extra_frontmatter) if extra_frontmatter else {}
        self._body = body

    @property
    def entity(self) -> Entity:
        """The validated domain Entity."""
        return self._entity

    @property
    def extra_frontmatter(self) -> dict[str, object]:
        """YAML frontmatter keys not covered by the domain Entity schema.

        Returns a copy to prevent accidental mutation of stored data.
        """
        return dict(self._extra_frontmatter)

    @property
    def body(self) -> str:
        """The Markdown body text after the frontmatter block."""
        return self._body

    def __repr__(self) -> str:
        return (
            f"VaultDocument(entity_id={self._entity.id!r}, "
            f"entity_type={self._entity.type.value!r}, "
            f"extra_fields={len(self._extra_frontmatter)}, "
            f"body_len={len(self._body)})"
        )


# ── VaultRepository protocol ───────────────────────────────────────────────


@runtime_checkable
class VaultRepository(Protocol):
    """Protocol for the trusted Vault persistence layer.

    The VaultRepository owns all Obsidian Vault read/write operations
    for campaign entities.  It enforces:

    - stable identity (``EntityId``, not filename);
    - atomic writes with temporary-file-then-replace semantics;
    - optimistic concurrency through ``Revision`` checking;
    - path safety (no traversal outside the Vault root);
    - Markdown body preservation across read/write cycles;
    - audit logging of all mutation operations.

    Implementation is owned by Stage 3 (Vault Repository).  This protocol
    is defined here so that upper layers can depend on the contract
    without waiting for the full implementation.
    """

    def create_entity(self, document: VaultDocument) -> VaultDocument:
        """Persist a new entity document in the Vault.

        Args:
            document: The entity document to create.  Must have a unique
                ``EntityId`` that does not already exist in the Vault.

        Returns:
            The persisted document as stored (may include storage-assigned
            metadata such as ``updated_at``).

        Raises:
            ConflictError: An entity with the same ``EntityId`` already
                exists.
            StorageError: The write operation failed.
        """
        ...

    def get_entity(self, entity_id: EntityId) -> VaultDocument:
        """Retrieve an entity document by its stable ID.

        Args:
            entity_id: The stable domain identifier.

        Returns:
            The matching VaultDocument.

        Raises:
            NotFoundError: No entity with the given ID exists.
            StorageError: The read operation failed.
        """
        ...

    def list_entities(
        self,
        entity_type: EntityType | None = None,
    ) -> list[VaultDocument]:
        """List entity documents in the Vault.

        Args:
            entity_type: Optional filter by entity type.  When ``None``,
                all entity types are returned.

        Returns:
            A list of matching VaultDocuments.  Returns an empty list
            when no entities match.
        """
        ...

    # patch_entity — deferred to S3-06
    #
    # The typed signature for patch_entity cannot be finalised until
    # S3-06 establishes:
    #   - the patch DTO shape (field-level vs full-document);
    #   - revision increment ownership (caller vs storage).
    #
    # Stable requirements documented now:
    #   - targets an EntityId;
    #   - uses expected_revision for optimistic concurrency;
    #   - mismatch raises ConflictError;
    #   - successful revision-update semantics are finalised in S3-06.
    #
    # See S3-00 completion record and S3-06 task for the deferral rationale.

    def append_entity_fact(
        self,
        entity_id: EntityId,
        *,
        expected_revision: Revision,
        fact: str,
    ) -> VaultDocument:
        """Append a fact/note to an entity's Markdown body.

        This is a specialised append operation that adds structured
        information to the entity's body without requiring the caller
        to read, modify, and write the entire document.

        Args:
            entity_id: The stable domain identifier of the entity.
            expected_revision: The revision the caller last observed.
            fact: The fact text to append.

        Returns:
            The updated document as stored (revision-update semantics
            are finalised in S3-07).

        Raises:
            NotFoundError: No entity with the given ID exists.
            ConflictError: The stored revision does not match
                ``expected_revision``.
            StorageError: The write operation failed.
        """
        ...
