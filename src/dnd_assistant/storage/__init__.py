"""Storage layer: Vault persistence, audit logging, and document representation."""

from dnd_assistant.storage.atomic import atomic_write_text
from dnd_assistant.storage.audit import AuditContext, AuditRecord, AuditService
from dnd_assistant.storage.markdown import parse, serialize
from dnd_assistant.storage.patch import EntityPatch
from dnd_assistant.storage.paths import (
    DiscoveredEntityFile,
    discover_entity_files,
    entity_directory,
    resolve_entity_path,
)
from dnd_assistant.storage.session_paths import (
    SessionStoragePaths,
    resolve_session_storage_paths,
)
from dnd_assistant.storage.types import (
    EntityDirectory,
    VaultDocument,
    VaultRepository,
    WorldTimeRepository,
)
from dnd_assistant.storage.vault_repository import ObsidianVaultRepository
from dnd_assistant.storage.world_time import ObsidianWorldTimeRepository

__all__: list[str] = [
    "AuditContext",
    "AuditRecord",
    "AuditService",
    "DiscoveredEntityFile",
    "EntityDirectory",
    "EntityPatch",
    "ObsidianVaultRepository",
    "ObsidianWorldTimeRepository",
    "SessionStoragePaths",
    "VaultDocument",
    "VaultRepository",
    "WorldTimeRepository",
    "atomic_write_text",
    "discover_entity_files",
    "entity_directory",
    "parse",
    "resolve_entity_path",
    "resolve_session_storage_paths",
    "serialize",
]
