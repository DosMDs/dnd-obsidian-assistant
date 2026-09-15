"""S11-01 post-session processing test fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from dnd_assistant.storage.audit import AuditService
from dnd_assistant.storage.post_session_processing import (
    ObsidianPostSessionProcessingStore,
)
from dnd_assistant.storage.session_metadata import ObsidianSessionMetadataRepository
from tests.unit.post_session.helpers import make_audit_service, make_vault


@pytest.fixture
def vault_root(tmp_path: Path) -> Path:
    return make_vault(tmp_path)


@pytest.fixture
def audit_service(vault_root: Path) -> AuditService:
    return make_audit_service(vault_root)


@pytest.fixture
def metadata_repo(
    vault_root: Path, audit_service: AuditService
) -> ObsidianSessionMetadataRepository:
    return ObsidianSessionMetadataRepository(vault_root, audit_service)


@pytest.fixture
def store(vault_root: Path) -> ObsidianPostSessionProcessingStore:
    return ObsidianPostSessionProcessingStore(vault_root)
