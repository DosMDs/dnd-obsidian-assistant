"""Shared fixtures for S3-08 Vault Repository integration tests.

Establishes a minimal real temporary Obsidian Vault with:
- canonical entity directories (Characters/NPCs, Locations, Quests, Items);
- _system/audit/ directory;
- a real AuditService;
- a real ObsidianVaultRepository.

No real campaign Vault, no Ollama, no network, no shell subprocess.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dnd_assistant.domain.types import EntityType
from dnd_assistant.storage.audit import AuditService
from dnd_assistant.storage.paths import entity_directory
from dnd_assistant.storage.vault_repository import ObsidianVaultRepository


@pytest.fixture
def vault_root(tmp_path: Path) -> Path:
    root = tmp_path / "vault"
    root.mkdir()

    audit_dir = root / "_system" / "audit"
    audit_dir.mkdir(parents=True)

    for entity_type in EntityType:
        edir = entity_directory(root, entity_type)
        edir.mkdir(parents=True)

    return root


@pytest.fixture
def audit_service(vault_root: Path) -> AuditService:
    audit_log = vault_root / "_system" / "audit" / "audit.jsonl"
    return AuditService(audit_log)


@pytest.fixture
def audit_log_path(vault_root: Path) -> Path:
    return vault_root / "_system" / "audit" / "audit.jsonl"


@pytest.fixture
def repo(vault_root: Path, audit_service: AuditService) -> ObsidianVaultRepository:
    return ObsidianVaultRepository(vault_root, audit_service)
