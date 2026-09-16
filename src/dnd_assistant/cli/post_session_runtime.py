"""S11-07 POST_SESSION CLI runtime composition and model lifetime.

This module owns only the focused ``dnd session process`` concerns that do not
belong to Typer presentation or to the accepted application/storage layers:

- POST_SESSION-role profile loading (never the AGENT-only contract);
- deterministic ``--latest`` completed-session selection over validated
  metadata (no filesystem mtime/enumeration inference);
- concrete dependency composition for the accepted S11-06 processor using the
  real Obsidian stores;
- owning the underlying Pydantic AI model lifetime (idempotent close).

It does NOT own eligibility, prepared-input assembly, ledger folding, attempt
claiming, entity resolution, ChangeSet construction, artifact/proposal
persistence policy, failure categorization, prompts or result rendering.

This module is a CLI-layer composition module: concrete storage imports are
expected and allowed here.  The application processor remains protocol-only.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from enum import StrEnum
from pathlib import Path

from pydantic_ai.models import Model

from dnd_assistant.application.post_session_clock import PostSessionClock, system_utc_now
from dnd_assistant.application.post_session_extraction import ModelExecutionIdentity
from dnd_assistant.application.post_session_identity import new_attempt_id
from dnd_assistant.application.post_session_processor import (
    PostSessionProcessorDeps,
    run_post_session_processing,
)
from dnd_assistant.application.post_session_processor_support import (
    PostSessionProcessorResult,
)
from dnd_assistant.application.pydantic_ai_post_session import (
    PydanticAIPostSessionExtractionModel,
)
from dnd_assistant.application.pydantic_ai_post_session_rendering import (
    PydanticAIPostSessionRenderingModel,
)
from dnd_assistant.errors import DndAssistantError, ValidationError
from dnd_assistant.models.profiles import (
    ModelProfile,
    ModelProfileRole,
    load_model_profiles,
)
from dnd_assistant.models.pydantic_ai_ollama import build_pydantic_ai_post_session_model
from dnd_assistant.storage.audit import AuditService
from dnd_assistant.storage.changeset_store import ObsidianChangeSetStore
from dnd_assistant.storage.post_session_artifacts import ObsidianPostSessionArtifactStore
from dnd_assistant.storage.post_session_processing import ObsidianPostSessionProcessingStore
from dnd_assistant.storage.session_events import ObsidianSessionEventRepository
from dnd_assistant.storage.session_metadata import (
    ObsidianSessionMetadataRepository,
    RawSessionMetadata,
)
from dnd_assistant.storage.vault_repository import ObsidianVaultRepository

__all__ = [
    "LatestSelectionError",
    "LatestSelectionReason",
    "PostSessionRuntime",
    "compose_metadata_repository",
    "compose_post_session_runtime",
    "new_attempt_id",
    "select_latest_completed_session",
]

# ── Latest-session selection ──────────────────────────────────────────────


class LatestSelectionReason(StrEnum):
    """Bounded reason ``--latest`` could not select a completed session."""

    NO_COMPLETED_SESSIONS = "no_completed_sessions"
    MISSING_FINISH_METADATA = "missing_finish_metadata"


class LatestSelectionError(DndAssistantError):
    """Deterministic ``--latest`` selection failure (fail closed)."""

    def __init__(
        self,
        reason: LatestSelectionReason,
        session_ids: Sequence[str] = (),
    ) -> None:
        if reason is LatestSelectionReason.NO_COMPLETED_SESSIONS:
            message = "Завершённых сессий не найдено."
        else:
            names = ", ".join(session_ids)
            message = (
                "У завершённой сессии отсутствует время окончания, "
                f"выбор --latest невозможен: {names}."
            )
        super().__init__(message)
        self.reason = reason
        self.session_ids = tuple(session_ids)


_NUMERIC_SESSION_ID_RE = re.compile(r"^S(\d+)$")


def _id_rank(session_id: str) -> tuple[int, int, str]:
    """Return a deterministic, numeric-aware total-order rank for a session id.

    Numeric ``S<n>`` ids sort numerically (``S2`` before ``S10``) and outrank
    non-numeric ids, which fall back to their exact string value.
    """
    match = _NUMERIC_SESSION_ID_RE.match(session_id)
    if match is not None:
        return (0, int(match.group(1)), "")
    return (1, 0, session_id)


def select_latest_completed_session(
    metadatas: Sequence[RawSessionMetadata],
) -> str:
    """Select the latest completed session deterministically (pure).

    ``latest`` is the completed session with the greatest canonical
    ``real_finished_at``; ``_id_rank`` is the deterministic total-order
    tie-breaker.  A completed record missing required finish metadata fails
    closed instead of being skipped, so a newer malformed completed session is
    never silently bypassed in favor of an older one.

    Raises:
        LatestSelectionError: No completed session exists, or a completed
            record lacks required finish metadata.
    """
    completed = [meta for meta in metadatas if meta.session.status == "completed"]
    if not completed:
        raise LatestSelectionError(LatestSelectionReason.NO_COMPLETED_SESSIONS)

    missing = sorted(meta.session.id for meta in completed if meta.session.real_finished_at is None)
    if missing:
        raise LatestSelectionError(LatestSelectionReason.MISSING_FINISH_METADATA, missing)

    latest = max(
        completed,
        key=lambda meta: (meta.session.real_finished_at, _id_rank(meta.session.id)),
    )
    return latest.session.id


# ── Profile loading (POST_SESSION role only) ──────────────────────────────


def _load_post_session_profile(config_path: Path, profile_name: str) -> ModelProfile:
    """Load and validate the exact POST_SESSION profile.

    Raises:
        DndAssistantError: The config is unreadable/invalid, the profile is
            missing, or the profile has a non-POST_SESSION role.
    """
    config = load_model_profiles(config_path)

    if profile_name not in config.profiles:
        raise ValidationError(f"Профиль '{profile_name}' не найден в конфигурации")

    profile = config.profiles[profile_name]

    if profile.role is not ModelProfileRole.POST_SESSION:
        raise ValidationError(
            f"Профиль '{profile_name}' имеет роль '{profile.role.value}', "
            f"ожидается '{ModelProfileRole.POST_SESSION.value}'"
        )

    return profile


# ── Model factory seam (testable) ─────────────────────────────────────────


def _build_post_session_model(profile: ModelProfile) -> Model:
    """Construct a Pydantic AI ``Model`` via the accepted POST_SESSION factory.

    Narrow test seam — automated tests replace this function to inject a
    deterministic Pydantic AI ``Model`` without changing production wiring.
    """
    return build_pydantic_ai_post_session_model(profile)


def _close_model(model: Model) -> None:
    """Release model resources if the concrete model exposes a close hook."""
    close = getattr(model, "close", None)
    if callable(close):
        close()


# ── Metadata repository composition (selector resolution) ─────────────────


def compose_metadata_repository(vault_root: Path) -> ObsidianSessionMetadataRepository:
    """Compose a read-capable session metadata repository for selector work."""
    audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
    audit_service = AuditService(str(audit_log_path))
    return ObsidianSessionMetadataRepository(vault_root, audit_service)


# ── Runtime ────────────────────────────────────────────────────────────────


class PostSessionRuntime:
    """Composed POST_SESSION runtime for one ``dnd session process`` invocation.

    Owns the underlying Pydantic AI model lifetime; ``close()`` is idempotent
    and must be called after the command completes.
    """

    def __init__(
        self,
        *,
        model: Model,
        deps: PostSessionProcessorDeps,
        model_identity: ModelExecutionIdentity,
        vault_root: Path,
        profile_name: str,
    ) -> None:
        self._model = model
        self._closed = False
        self.deps = deps
        self.model_identity = model_identity
        self.vault_root = vault_root
        self.profile_name = profile_name

    @property
    def model(self) -> Model:
        """The underlying Pydantic AI model shared by both adapters."""
        return self._model

    def close(self) -> None:
        """Release model resources exactly once (safe to call repeatedly)."""
        if not self._closed:
            self._closed = True
            _close_model(self._model)

    def run(
        self,
        session_id: str,
        attempt_id: str,
        *,
        clock: PostSessionClock = system_utc_now,
    ) -> PostSessionProcessorResult:
        """Run the accepted S11-06 processor with the trusted execution identity."""
        return run_post_session_processing(
            self.deps,
            session_id,
            attempt_id,
            model_identity=self.model_identity,
            clock=clock,
        )


def compose_post_session_runtime(
    *,
    vault_root: Path,
    config_path: Path,
    profile_name: str,
    model_factory: Callable[[ModelProfile], Model] | None = None,
) -> PostSessionRuntime:
    """Compose the focused POST_SESSION runtime for one invocation.

    The caller must call ``.close()`` after use.  A composition failure after
    model creation closes the model before propagating.

    Raises:
        DndAssistantError: Profile loading, model construction or dependency
            composition failed.
    """
    profile = _load_post_session_profile(config_path, profile_name)

    factory = model_factory or _build_post_session_model
    model = factory(profile)

    with ExitStack() as stack:
        stack.callback(_close_model, model)

        audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        audit_service = AuditService(str(audit_log_path))

        deps = PostSessionProcessorDeps(
            metadata_repo=ObsidianSessionMetadataRepository(vault_root, audit_service),
            event_repo=ObsidianSessionEventRepository(vault_root, audit_service),
            vault_repo=ObsidianVaultRepository(
                vault_root=str(vault_root),
                audit_service=audit_service,
            ),
            processing_store=ObsidianPostSessionProcessingStore(vault_root),
            artifact_store=ObsidianPostSessionArtifactStore(vault_root),
            changeset_store=ObsidianChangeSetStore(vault_root),
            extraction_model=PydanticAIPostSessionExtractionModel(model=model),
            rendering_model=PydanticAIPostSessionRenderingModel(model=model),
        )

        model_identity = ModelExecutionIdentity(
            profile=profile_name,
            model=profile.model,
            provider=profile.provider,
        )

        runtime = PostSessionRuntime(
            model=model,
            deps=deps,
            model_identity=model_identity,
            vault_root=vault_root,
            profile_name=profile_name,
        )

        # Transfer model ownership to the runtime; ExitStack must not close it
        # on the normal path.
        stack.pop_all()

    return runtime
