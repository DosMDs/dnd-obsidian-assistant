"""S11-06 terminal-attempt integrity verification.

The structural ledger fold (``application.post_session_attempt_state``) never
enforces S11-06 artifact/proposal inventory.  This module owns that separate
concern: for a structurally ``COMPLETED`` attempt it verifies that every
required durable output exists, matches its recorded content hash and path, and
agrees with the ledger's terminal outcome.

A failure here means **terminal evidence is incomplete/inconsistent**, not that
the append-only ledger is corrupt.  The ledger is never reclassified, rewritten
or migrated.  Legacy completed ledger history therefore remains structurally
``COMPLETED`` while integrity verification reports why it cannot be treated as a
fully verified S11-06 result.

This module belongs to the application layer and must not import from:
    models, ollama, pydantic_ai, tools, cli, retrieval, pathlib, os, or a
    concrete storage implementation (storage protocols are referenced only
    under ``TYPE_CHECKING``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from dnd_assistant.application.changeset_review import (
    compute_changeset_fingerprint,
)
from dnd_assistant.application.changeset_store import deserialize_proposal
from dnd_assistant.application.post_session_attempt_state import (
    AttemptState,
    AttemptStateFold,
)
from dnd_assistant.application.post_session_persistence import artifact_content_hash
from dnd_assistant.domain.post_session import (
    AttemptCompleted,
    PersistedArtifactKind,
    ProcessingOutcome,
)
from dnd_assistant.domain.post_session_workflow import AttemptWorkflowEvidence
from dnd_assistant.errors import DndAssistantError, NotFoundError, StorageError

if TYPE_CHECKING:
    from dnd_assistant.storage.changeset_store import ChangeSetStore
    from dnd_assistant.storage.post_session_artifacts import PostSessionArtifactStore

_REQUIRED_SLOTS: Final[tuple[PersistedArtifactKind, ...]] = (
    PersistedArtifactKind.SUMMARY,
    PersistedArtifactKind.RECAP,
    PersistedArtifactKind.WORKFLOW,
)


class TerminalIntegrityReason(StrEnum):
    """Bounded reason a structurally terminal attempt lacks valid evidence."""

    TERMINAL_EVIDENCE_INCOMPLETE = "terminal_evidence_incomplete"
    ARTIFACT_MISSING = "artifact_missing"
    ARTIFACT_HASH_MISMATCH = "artifact_hash_mismatch"
    ARTIFACT_PATH_MISMATCH = "artifact_path_mismatch"
    PROPOSAL_MISSING = "proposal_missing"
    PROPOSAL_FINGERPRINT_MISMATCH = "proposal_fingerprint_mismatch"
    UNEXPECTED_PROPOSAL = "unexpected_proposal"
    WORKFLOW_EVIDENCE_INVALID = "workflow_evidence_invalid"
    WORKFLOW_EVIDENCE_INCONSISTENT = "workflow_evidence_inconsistent"


@dataclass(frozen=True)
class TerminalIntegrityResult:
    """Outcome of terminal integrity verification."""

    ok: bool
    reason: TerminalIntegrityReason | None = None


def _fail(reason: TerminalIntegrityReason) -> TerminalIntegrityResult:
    return TerminalIntegrityResult(ok=False, reason=reason)


def _parse_workflow(text: str) -> AttemptWorkflowEvidence | None:
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    try:
        return AttemptWorkflowEvidence.model_validate(data)
    except Exception:
        return None


def verify_terminal_integrity(
    fold: AttemptStateFold,
    session_id: str,
    *,
    artifact_store: PostSessionArtifactStore,
    changeset_store: ChangeSetStore,
) -> TerminalIntegrityResult:
    """Verify a structurally ``COMPLETED`` attempt's durable evidence.

    Returns ``ok=True`` for non-``COMPLETED`` states (there is no completed
    inventory to verify).  Any missing/inconsistent evidence fails closed.
    """
    if fold.state is not AttemptState.COMPLETED:
        return TerminalIntegrityResult(ok=True)

    terminal = fold.terminal
    if not isinstance(terminal, AttemptCompleted):
        return _fail(TerminalIntegrityReason.TERMINAL_EVIDENCE_INCOMPLETE)

    started = fold.started
    if started is None:
        return _fail(TerminalIntegrityReason.TERMINAL_EVIDENCE_INCOMPLETE)

    # 1. Required artifact slots are recorded in the ledger.
    for kind in _REQUIRED_SLOTS:
        if kind not in fold.artifacts:
            return _fail(TerminalIntegrityReason.TERMINAL_EVIDENCE_INCOMPLETE)

    # 2. Each recorded artifact exists, matches its hash and expected path.
    texts: dict[PersistedArtifactKind, str] = {}
    for kind, event in fold.artifacts.items():
        text = artifact_store.read_artifact_if_present(session_id, fold.attempt_id, kind)
        if text is None:
            return _fail(TerminalIntegrityReason.ARTIFACT_MISSING)
        texts[kind] = text
        if artifact_content_hash(text).digest != event.content_hash.digest:
            return _fail(TerminalIntegrityReason.ARTIFACT_HASH_MISMATCH)
        expected_path = artifact_store.expected_relative_path(session_id, fold.attempt_id, kind)
        if event.relative_path != expected_path:
            return _fail(TerminalIntegrityReason.ARTIFACT_PATH_MISMATCH)

    # 3. Workflow evidence parses, binds this attempt and agrees on the outcome.
    workflow = _parse_workflow(texts[PersistedArtifactKind.WORKFLOW])
    if workflow is None:
        return _fail(TerminalIntegrityReason.WORKFLOW_EVIDENCE_INVALID)
    if (
        workflow.session_ref != started.session_ref
        or workflow.attempt_id != fold.attempt_id
        or workflow.input_fingerprint.digest != started.input_fingerprint.digest
    ):
        return _fail(TerminalIntegrityReason.WORKFLOW_EVIDENCE_INCONSISTENT)

    produced = terminal.outcome is ProcessingOutcome.PRODUCED
    if workflow.change_plan.produced != produced:
        return _fail(TerminalIntegrityReason.WORKFLOW_EVIDENCE_INCONSISTENT)

    # 4. Proposal presence and fingerprint agree with the terminal outcome.
    if produced:
        if fold.proposal is None:
            return _fail(TerminalIntegrityReason.TERMINAL_EVIDENCE_INCOMPLETE)
        try:
            persisted_text = changeset_store.read_proposal(fold.proposal.changeset_id)
        except NotFoundError:
            return _fail(TerminalIntegrityReason.PROPOSAL_MISSING)
        except StorageError:
            return _fail(TerminalIntegrityReason.PROPOSAL_MISSING)
        try:
            proposal = deserialize_proposal(persisted_text)
        except (StorageError, DndAssistantError):
            return _fail(TerminalIntegrityReason.PROPOSAL_MISSING)
        if proposal.changeset_id != fold.proposal.changeset_id:
            return _fail(TerminalIntegrityReason.PROPOSAL_FINGERPRINT_MISMATCH)
        fingerprint = compute_changeset_fingerprint(proposal)
        if fingerprint.digest != fold.proposal.changeset_fingerprint.digest:
            return _fail(TerminalIntegrityReason.PROPOSAL_FINGERPRINT_MISMATCH)
        if (
            workflow.change_plan.changeset_id != fold.proposal.changeset_id
            or workflow.change_plan.changeset_fingerprint is None
            or workflow.change_plan.changeset_fingerprint.digest != fingerprint.digest
        ):
            return _fail(TerminalIntegrityReason.WORKFLOW_EVIDENCE_INCONSISTENT)
    else:
        if fold.proposal is not None:
            return _fail(TerminalIntegrityReason.UNEXPECTED_PROPOSAL)
        # A NO_CHANGES terminal additionally requires that no orphan Stage-10
        # proposal exists for this attempt's deterministic changeset id, even
        # when no proposal_persisted ledger event was recorded.  The orphan's
        # existence is integrity evidence only: it never alters the ledger fold
        # and is never deleted or mutated by verification.
        candidate_id = f"cs_{started.session_ref}_{fold.attempt_id}"
        try:
            orphan_text = changeset_store.read_proposal_if_present(candidate_id)
        except StorageError:
            # Malformed/unreadable candidate state fails closed, never treated
            # as absent.
            return _fail(TerminalIntegrityReason.UNEXPECTED_PROPOSAL)
        if orphan_text is not None:
            return _fail(TerminalIntegrityReason.UNEXPECTED_PROPOSAL)

    return TerminalIntegrityResult(ok=True)


__all__ = [
    "TerminalIntegrityReason",
    "TerminalIntegrityResult",
    "verify_terminal_integrity",
]
