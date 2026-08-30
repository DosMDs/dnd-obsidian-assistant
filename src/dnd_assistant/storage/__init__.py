"""Storage layer: Vault persistence, audit logging, and document representation."""

from dnd_assistant.storage.atomic import atomic_write_text
from dnd_assistant.storage.audit import AuditRecord, AuditService
from dnd_assistant.storage.markdown import parse, serialize
from dnd_assistant.storage.paths import (
    DiscoveredEntityFile,
    discover_entity_files,
    entity_directory,
    resolve_entity_path,
)
from dnd_assistant.storage.types import EntityDirectory, VaultDocument, VaultRepository

__all__: list[str] = [
    "AuditRecord",
    "AuditService",
    "DiscoveredEntityFile",
    "EntityDirectory",
    "VaultDocument",
    "VaultRepository",
    "atomic_write_text",
    "discover_entity_files",
    "entity_directory",
    "parse",
    "resolve_entity_path",
    "serialize",
]
