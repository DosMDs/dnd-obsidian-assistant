"""S13-03 bootstrap discovery/mapping runtime composition.

Owns concrete dependency construction and orchestration for the bootstrap
workflow so presentation surfaces stay free of storage details:

- composes the accepted S13-02 read-only discovery service;
- recognizes canonical entities from the already-read ``ENTITY_CANDIDATE``
  report data (no second filesystem traversal);
- composes the BOOTSTRAP-role Pydantic AI model and owns its lifetime;
- persists the produced proposal and immutable mapping evidence.

It contains no Russian text and no ``typer``/``textual`` types.  It does not
perform review, approval or apply.

This module is a composition layer and may import concrete storage.
"""

from __future__ import annotations

from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path

from pydantic_ai.models import Model

from dnd_assistant.application.bootstrap_changeset import BootstrapMappingOutcome
from dnd_assistant.application.bootstrap_evidence import (
    BootstrapEvidenceRecord,
    EvidencePersistOutcome,
    build_bootstrap_evidence,
    persist_bootstrap_evidence,
)
from dnd_assistant.application.bootstrap_mapping import (
    BOOTSTRAP_PROCESSOR_VERSION,
    BootstrapMappingRun,
    BootstrapModelIdentity,
    run_bootstrap_mapping,
)
from dnd_assistant.application.changeset_store import (
    ProposalPersistOutcome,
    persist_proposal,
)
from dnd_assistant.application.vault_discovery import (
    ContentReadStatus,
    SourceClass,
    VaultDiscoveryReport,
    VaultDiscoveryService,
)
from dnd_assistant.errors import ConflictError, StorageError, ValidationError
from dnd_assistant.models.profiles import (
    ModelProfile,
    ModelProfileRole,
    load_model_profiles,
)
from dnd_assistant.models.pydantic_ai_ollama import build_pydantic_ai_bootstrap_model
from dnd_assistant.storage.bootstrap_canonical import parse_canonical_candidate
from dnd_assistant.storage.bootstrap_evidence import ObsidianBootstrapEvidenceStore
from dnd_assistant.storage.bootstrap_types import CanonicalCandidate
from dnd_assistant.storage.changeset_store import ObsidianChangeSetStore
from dnd_assistant.storage.vault_discovery import ObsidianVaultSourceReader

__all__ = [
    "BootstrapRuntime",
    "BootstrapRuntimeResult",
    "canonical_candidates_from_report",
    "compose_bootstrap_discovery",
    "compose_bootstrap_runtime",
]


# ── Discovery + recognition ───────────────────────────────────────────────


def compose_bootstrap_discovery(vault_root: Path) -> VaultDiscoveryReport:
    """Compose the accepted S13-02 read-only discovery service and run it."""
    reader = ObsidianVaultSourceReader(vault_root)
    return VaultDiscoveryService(reader).run()


def canonical_candidates_from_report(
    report: VaultDiscoveryReport,
) -> tuple[CanonicalCandidate, ...]:
    """Recognize canonical entities from already-read ``ENTITY_CANDIDATE`` data.

    No filesystem traversal occurs here: only entries S13-02 already read are
    parsed through the filesystem-free canonical parse helper.
    """
    candidates: list[CanonicalCandidate] = []
    for entry in report.entries:
        if entry.source_class is not SourceClass.ENTITY_CANDIDATE:
            continue
        if entry.content_status is not ContentReadStatus.READ or entry.content_text is None:
            continue
        candidates.append(parse_canonical_candidate(entry.relative_path, entry.content_text))
    return tuple(candidates)


# ── Profile + model ───────────────────────────────────────────────────────


def _load_bootstrap_profile(config_path: Path, profile_name: str) -> ModelProfile:
    """Load and validate the exact BOOTSTRAP-role profile."""
    config = load_model_profiles(config_path)
    if profile_name not in config.profiles:
        raise ValidationError(f"Профиль '{profile_name}' не найден в конфигурации")
    profile = config.profiles[profile_name]
    if profile.role is not ModelProfileRole.BOOTSTRAP:
        raise ValidationError(
            f"Профиль '{profile_name}' имеет роль '{profile.role.value}', "
            f"ожидается '{ModelProfileRole.BOOTSTRAP.value}'"
        )
    return profile


def _build_bootstrap_model(profile: ModelProfile) -> Model:
    """Construct the BOOTSTRAP Pydantic AI model (test seam)."""
    return build_pydantic_ai_bootstrap_model(profile)


def _close_model(model: Model) -> None:
    """Release model resources if the concrete model exposes a close hook."""
    close = getattr(model, "close", None)
    if callable(close):
        close()


# ── Runtime result ────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class BootstrapRuntimeResult:
    """Result of one bootstrap mapping/persistence invocation."""

    run: BootstrapMappingRun
    proposal_outcome: ProposalPersistOutcome | None = None
    evidence_outcome: EvidencePersistOutcome | None = None
    evidence_record: BootstrapEvidenceRecord | None = None
    evidence_error: str | None = None

    @property
    def is_proposal(self) -> bool:
        return self.run.result.outcome is BootstrapMappingOutcome.PROPOSAL

    @property
    def partial_persistence(self) -> bool:
        """True when a proposal was persisted but evidence persistence failed."""
        return self.proposal_outcome is not None and self.evidence_error is not None


# ── Runtime ───────────────────────────────────────────────────────────────


class BootstrapRuntime:
    """Composed BOOTSTRAP runtime for one ``dnd bootstrap map`` invocation."""

    def __init__(
        self,
        *,
        model: Model,
        model_identity: BootstrapModelIdentity,
        vault_root: Path,
        profile_name: str,
        changeset_store: ObsidianChangeSetStore,
        evidence_store: ObsidianBootstrapEvidenceStore,
    ) -> None:
        self._model = model
        self._closed = False
        self.model_identity = model_identity
        self.vault_root = vault_root
        self.profile_name = profile_name
        self._changeset_store = changeset_store
        self._evidence_store = evidence_store

    def close(self) -> None:
        """Release model resources exactly once (safe to call repeatedly)."""
        if not self._closed:
            self._closed = True
            _close_model(self._model)

    def run(
        self,
        report: VaultDiscoveryReport,
        *,
        persist: bool = True,
    ) -> BootstrapRuntimeResult:
        """Map the report to a proposal and, unless ``persist`` is false, persist.

        Persistence order is proposal first, evidence second.  An evidence
        persistence failure is reported truthfully as partial workflow
        persistence: the proposal remains persisted, no rollback is performed
        and no review readiness is claimed.
        """
        from dnd_assistant.application.pydantic_ai_bootstrap import (
            PydanticAIBootstrapExtractionModel,
        )

        model = PydanticAIBootstrapExtractionModel(model=self._model)
        candidates = canonical_candidates_from_report(report)
        run = run_bootstrap_mapping(
            report,
            candidates,
            model,
            processor_version=BOOTSTRAP_PROCESSOR_VERSION,
            model_identity=self.model_identity,
        )

        if not run.result.changeset or not persist:
            return BootstrapRuntimeResult(run=run)

        proposal_outcome = persist_proposal(self._changeset_store, run.result.changeset)

        evidence_record = build_bootstrap_evidence(
            run.projection,
            run.result,
            producer_version=run.processor_version,
            prompt_version=run.prompt_version,
            extraction_schema_version=run.extraction_schema_version,
            model_profile=run.model_identity.profile,
            model=run.model_identity.model,
            provider=run.model_identity.provider,
        )
        try:
            evidence_outcome = persist_bootstrap_evidence(self._evidence_store, evidence_record)
        except (ConflictError, StorageError) as exc:
            return BootstrapRuntimeResult(
                run=run,
                proposal_outcome=proposal_outcome,
                evidence_record=evidence_record,
                evidence_error=str(exc),
            )

        return BootstrapRuntimeResult(
            run=run,
            proposal_outcome=proposal_outcome,
            evidence_outcome=evidence_outcome,
            evidence_record=evidence_record,
        )


def compose_bootstrap_runtime(
    *,
    vault_root: Path,
    config_path: Path,
    profile_name: str,
    model_factory: Callable[[ModelProfile], Model] | None = None,
) -> BootstrapRuntime:
    """Compose the focused BOOTSTRAP runtime for one invocation.

    The caller must call ``.close()`` after use.  A composition failure after
    model creation closes the model before propagating.
    """
    profile = _load_bootstrap_profile(config_path, profile_name)
    factory = model_factory or _build_bootstrap_model
    model = factory(profile)

    with ExitStack() as stack:
        stack.callback(_close_model, model)
        runtime = BootstrapRuntime(
            model=model,
            model_identity=BootstrapModelIdentity(
                profile=profile_name,
                model=profile.model,
                provider=profile.provider,
            ),
            vault_root=vault_root,
            profile_name=profile_name,
            changeset_store=ObsidianChangeSetStore(vault_root),
            evidence_store=ObsidianBootstrapEvidenceStore(vault_root),
        )
        stack.pop_all()

    return runtime
