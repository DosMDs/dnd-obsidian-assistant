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
    from dnd_assistant.domain.calendar import WorldTick
    from dnd_assistant.domain.entity import Entity
    from dnd_assistant.domain.types import EntityId, Revision
    from dnd_assistant.domain.world_time import CurrentWorldTime
    from dnd_assistant.storage.audit import AuditContext
    from dnd_assistant.storage.patch import EntityPatch


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

    def create_entity(
        self,
        document: VaultDocument,
        *,
        audit: AuditContext,
    ) -> VaultDocument:
        """Persist a new entity document in the Vault.

        Args:
            document: The entity document to create.  Must have a unique
                ``EntityId`` that does not already exist in the Vault.
            audit: Audit context for this mutation.  Every repository
                mutation must carry explicit audit metadata.

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

    def patch_entity(
        self,
        entity_id: EntityId,
        patch: EntityPatch,
        *,
        expected_revision: Revision,
        audit: AuditContext,
    ) -> VaultDocument:
        """Patch an existing entity's editable fields.

        Applies the supplied ``EntityPatch`` fields to the entity
        identified by ``entity_id``.  The operation is guarded by
        optimistic concurrency: the stored revision must match
        ``expected_revision`` or a ``ConflictError`` is raised.

        The repository owns revision increment (exactly +1) and
        ``updated_at`` (set to ``audit.real_time``).

        Args:
            entity_id: The stable domain identifier of the entity to patch.
            patch: The typed partial update DTO.
            expected_revision: The revision the caller last observed.
            audit: Audit context for this mutation.

        Returns:
            The persisted ``VaultDocument`` after the patch.

        Raises:
            ValidationError: The ``entity_id``, ``expected_revision``, or
                ``patch`` is invalid.
            NotFoundError: No entity with the given ID exists.
            ConflictError: The stored revision does not match
                ``expected_revision``, or the ``operation_id`` has already
                been used.
            StorageError: A filesystem or audit operation failed.
        """
        ...

    def append_entity_fact(
        self,
        entity_id: EntityId,
        *,
        expected_revision: Revision,
        fact: str,
        audit: AuditContext,
    ) -> VaultDocument:
        """Append a fact/note to an entity's Markdown body.

        This is a specialised append operation that adds structured
        information to the entity's body without requiring the caller
        to read, modify, and write the entire document.

        The fact is rendered as a single Markdown bullet (``"- <fact>\\n"``)
        appended to the existing body.  The existing body remains an exact
        character-for-character prefix of the new body.

        Args:
            entity_id: The stable domain identifier of the entity.
            expected_revision: The revision the caller last observed.
            fact: The fact text to append.  Must be non-empty, printable,
                with no leading/trailing whitespace or embedded newlines.
            audit: Audit context for this mutation.  Every repository
                mutation must carry explicit audit metadata.

        Returns:
            The updated document as stored (revision incremented by 1,
            ``updated_at`` set to ``audit.real_time``).

        Raises:
            ValidationError: The ``entity_id``, ``expected_revision``, or
                ``fact`` is invalid.
            NotFoundError: No entity with the given ID exists.
            ConflictError: The stored revision does not match
                ``expected_revision``.
            StorageError: A filesystem or audit operation failed.
        """
        ...


# ── WorldTimeRepository protocol ──────────────────────────────────────────


@runtime_checkable
class WorldTimeRepository(Protocol):
    """Protocol for current-world-time persistence.

    ``WorldTimeRepository`` owns read, initialize-once, and optimistic-update
    operations for the canonical ``_system/world_time.json`` state file.

    It is a separate persistence aggregate from ``VaultRepository`` —
    current world time is not an Entity and does not live in an entity
    directory.

    All mutations require explicit ``AuditContext``.
    """

    def get_current_world_time(self) -> CurrentWorldTime:
        """Read the canonical current world time.

        Returns:
            The validated ``CurrentWorldTime`` from the Vault.

        Raises:
            NotFoundError: No ``world_time.json`` exists.
            StorageError: The file is corrupt, malformed, or unreadable.
        """
        ...

    def initialize_current_world_time(
        self,
        world_tick: WorldTick,
        *,
        audit: AuditContext,
    ) -> CurrentWorldTime:
        """Initialize world time state with revision 1.

        This operation is valid only when no ``world_time.json`` exists.
        The caller supplies the canonical starting ``WorldTick``.

        Args:
            world_tick: The canonical starting world tick.
            audit: Audit context for this mutation.

        Returns:
            The persisted ``CurrentWorldTime`` with revision 1.

        Raises:
            ConflictError: State already exists (no silent overwrite).
            ValidationError: The ``world_tick`` is invalid.
            StorageError: A filesystem or audit operation failed.
        """
        ...

    def set_current_world_time(
        self,
        world_tick: WorldTick,
        *,
        expected_revision: Revision,
        audit: AuditContext,
    ) -> CurrentWorldTime:
        """Update the current world time with optimistic concurrency.

        The stored revision must match ``expected_revision`` or a
        ``ConflictError`` is raised.  On success, revision is incremented
        by exactly 1.

        Backward tick updates are accepted — monotonicity is not enforced
        by this repository (gameplay policy belongs to the application
        layer).

        Args:
            world_tick: The new canonical world tick.
            expected_revision: The revision the caller last observed.
            audit: Audit context for this mutation.

        Returns:
            The persisted ``CurrentWorldTime`` with incremented revision.

        Raises:
            NotFoundError: No ``world_time.json`` exists.
            ConflictError: The stored revision does not match
                ``expected_revision``.
            ValidationError: The ``world_tick`` or ``expected_revision``
                is invalid.
            StorageError: A filesystem or audit operation failed.
        """
        ...
