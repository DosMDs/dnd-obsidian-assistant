"""S11-08 literal canonical-campaign-truth snapshot helpers (test-only).

Campaign truth is compared as **exact file bytes**, never as repository-object
equality.  Legitimate Stage-11 workflow state (processing ledger/lock, attempt
artifacts, Stage-10 proposal artifacts) is excluded because S11-08 hardening
paths are allowed to create that state.
"""

from __future__ import annotations

from pathlib import Path

__all__ = [
    "WORKFLOW_STATE_HINT",
    "attempt_artifact_bytes",
    "canonical_truth_snapshot",
    "is_workflow_state",
]


def is_workflow_state(relative_path: str) -> bool:
    """Whether a Vault-relative path is legitimate Stage-11/Stage-10 workflow state."""
    if relative_path.startswith("_system/changesets/"):
        return True
    return relative_path.startswith("_system/raw/sessions/") and "/processing/" in relative_path


def canonical_truth_snapshot(root: Path) -> dict[str, bytes]:
    """Snapshot every canonical campaign-truth byte under ``root``.

    Includes entity Markdown, session ``metadata.json``/``events.jsonl``,
    ``_system/world_time.json`` when present and ``_system/audit/audit.jsonl``.
    Excludes processing ledger/lock, attempt artifacts and Stage-10 proposals.
    """
    result: dict[str, bytes] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        if is_workflow_state(relative):
            continue
        result[relative] = path.read_bytes()
    return result


def attempt_artifact_bytes(root: Path, session_id: str, attempt_id: str) -> dict[str, bytes]:
    """Return the exact bytes of every immutable artifact in one attempt namespace."""
    attempt_dir = (
        root / "_system" / "raw" / "sessions" / session_id / "processing" / "attempts" / attempt_id
    )
    result: dict[str, bytes] = {}
    if not attempt_dir.is_dir():
        return result
    for path in sorted(attempt_dir.iterdir()):
        if path.is_file():
            result[path.name] = path.read_bytes()
    return result


WORKFLOW_STATE_HINT = (
    "excluded prefixes: _system/changesets/ and _system/raw/sessions/*/processing/"
)
