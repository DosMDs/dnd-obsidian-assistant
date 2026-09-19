"""Storage layer: Vault persistence, audit logging, and document representation."""

from dnd_assistant.storage.atomic import atomic_write_text
from dnd_assistant.storage.audit import AuditContext, AuditRecord, AuditService
from dnd_assistant.storage.bootstrap_canonical import parse_canonical_candidate
from dnd_assistant.storage.bootstrap_evidence import (
    BootstrapEvidenceStore,
    ObsidianBootstrapEvidenceStore,
)
from dnd_assistant.storage.bootstrap_types import (
    CanonicalCandidate,
    CanonicalCandidateOutcome,
    expected_entity_type,
)
from dnd_assistant.storage.derived_state import (
    DerivedStateStore,
    ObsidianDerivedStateStore,
)
from dnd_assistant.storage.markdown import parse, serialize
from dnd_assistant.storage.patch import EntityPatch
from dnd_assistant.storage.paths import (
    DiscoveredEntityFile,
    discover_entity_files,
    entity_directory,
    resolve_entity_path,
)
from dnd_assistant.storage.session_events import (
    ObsidianSessionEventRepository,
    RawSessionEvent,
)
from dnd_assistant.storage.session_metadata import (
    ObsidianSessionMetadataRepository,
    RawSessionMetadata,
)
from dnd_assistant.storage.session_paths import (
    SessionStoragePaths,
    resolve_session_storage_paths,
)
from dnd_assistant.storage.session_recovery import (
    ObsidianSessionRecoveryRepository,
    RecoveryActionResult,
    RecoveryIssue,
    SessionRecoveryReport,
)
from dnd_assistant.storage.types import (
    EntityDirectory,
    SessionEventRepository,
    SessionMetadataRepository,
    SessionRecoveryRepository,
    VaultDocument,
    VaultRepository,
    WorldTimeRepository,
)
from dnd_assistant.storage.vault_discovery import (
    DiscoveryIssue,
    DiscoveryIssueCode,
    DiscoveryLimits,
    ExcludedEntry,
    InventoryEntry,
    ObsidianVaultSourceReader,
    SourceReadResult,
    VaultSourceInventory,
    VaultSourceReader,
)
from dnd_assistant.storage.vault_repository import ObsidianVaultRepository
from dnd_assistant.storage.world_time import ObsidianWorldTimeRepository

__all__: list[str] = [
    "AuditContext",
    "AuditRecord",
    "AuditService",
    "BootstrapEvidenceStore",
    "CanonicalCandidate",
    "CanonicalCandidateOutcome",
    "DerivedStateStore",
    "DiscoveredEntityFile",
    "DiscoveryIssue",
    "DiscoveryIssueCode",
    "DiscoveryLimits",
    "EntityDirectory",
    "ExcludedEntry",
    "EntityPatch",
    "InventoryEntry",
    "ObsidianDerivedStateStore",
    "ObsidianBootstrapEvidenceStore",
    "ObsidianSessionEventRepository",
    "ObsidianSessionMetadataRepository",
    "ObsidianSessionRecoveryRepository",
    "ObsidianVaultRepository",
    "ObsidianVaultSourceReader",
    "ObsidianWorldTimeRepository",
    "RawSessionEvent",
    "RawSessionMetadata",
    "RecoveryActionResult",
    "RecoveryIssue",
    "SessionEventRepository",
    "SessionMetadataRepository",
    "SessionRecoveryReport",
    "SessionRecoveryRepository",
    "SessionStoragePaths",
    "SourceReadResult",
    "VaultDocument",
    "VaultRepository",
    "VaultSourceInventory",
    "VaultSourceReader",
    "WorldTimeRepository",
    "atomic_write_text",
    "discover_entity_files",
    "entity_directory",
    "expected_entity_type",
    "parse",
    "parse_canonical_candidate",
    "resolve_entity_path",
    "resolve_session_storage_paths",
    "serialize",
]
