"""Shared structural stubs for read-only Vault repository test doubles.

Some tests only exercise the read side of ``VaultRepository``.  To satisfy the
full production protocol without duplicating mutation stubs in every test
module, those doubles can inherit :class:`VaultRepositoryWriteStubs` and
override only the read methods they actually implement.
"""

from __future__ import annotations

from dnd_assistant.domain.types import EntityId, Revision
from dnd_assistant.storage.audit import AuditContext
from dnd_assistant.storage.patch import EntityPatch
from dnd_assistant.storage.types import VaultDocument


class VaultRepositoryWriteStubs:
    """Mutation methods that read-only repository doubles never implement."""

    def create_entity(self, document: VaultDocument, *, audit: AuditContext) -> VaultDocument:
        msg = "Read-only repository double does not support writes"
        raise NotImplementedError(msg)

    def patch_entity(
        self,
        entity_id: EntityId,
        patch: EntityPatch,
        *,
        expected_revision: Revision,
        audit: AuditContext,
    ) -> VaultDocument:
        msg = "Read-only repository double does not support writes"
        raise NotImplementedError(msg)

    def append_entity_fact(
        self,
        entity_id: EntityId,
        *,
        expected_revision: Revision,
        fact: str,
        audit: AuditContext,
    ) -> VaultDocument:
        msg = "Read-only repository double does not support writes"
        raise NotImplementedError(msg)
