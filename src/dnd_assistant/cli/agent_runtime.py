"""S9-06 agent runtime composition — dependency wiring and provider lifetime.

This module owns S9-06-specific dependency composition and provider lifetime
management for the ``dnd ask`` CLI command.  It is NOT a general Bootstrap
framework (Stage 13 remains separate).

It composes the accepted concrete repositories, services, and tool layers
needed by the Fast Agent loop, then constructs the ``AgentLoop``.

Provider cleanup is guaranteed through a small context-manager runtime
object (``AskRuntime``) and ``contextlib.ExitStack`` during composition.
"""

from __future__ import annotations

from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from dnd_assistant.application.agent_context import AgentContextBuilder
from dnd_assistant.application.agent_loop import AgentLoop
from dnd_assistant.application.agent_tool_execution import AgentToolExecutionService
from dnd_assistant.application.session_recovery import SessionRecoveryService
from dnd_assistant.application.session_runtime import SessionRuntimeService
from dnd_assistant.errors import ValidationError
from dnd_assistant.models.profiles import ModelProfile, ModelProfileRole, load_model_profiles
from dnd_assistant.retrieval.index import SqliteFtsIndex
from dnd_assistant.retrieval.search import VaultSearchService
from dnd_assistant.storage.audit import AuditContext, AuditService
from dnd_assistant.storage.session_events import ObsidianSessionEventRepository
from dnd_assistant.storage.session_metadata import ObsidianSessionMetadataRepository
from dnd_assistant.storage.session_recovery import ObsidianSessionRecoveryRepository
from dnd_assistant.storage.vault_repository import ObsidianVaultRepository
from dnd_assistant.storage.world_time import ObsidianWorldTimeRepository
from dnd_assistant.tools.catalog import build_tool_registry_schema
from dnd_assistant.tools.entity_mutations import register_entity_mutation_tools
from dnd_assistant.tools.entity_reads import register_entity_read_tools
from dnd_assistant.tools.executor import ToolExecutor
from dnd_assistant.tools.registry import ToolRegistry
from dnd_assistant.tools.session_mutations import register_session_mutation_tools
from dnd_assistant.tools.session_reads import register_session_read_tools
from dnd_assistant.tools.types import ExecutionContext, Permission, SessionMode

if TYPE_CHECKING:
    pass


# ── Time and ID helpers (testable via monkeypatch) ─────────────────────────


def _now_utc() -> datetime:
    """Return the current UTC time with timezone awareness."""
    return datetime.now(UTC)


def _new_operation_id() -> str:
    """Return a unique operation ID for a model-tool invocation."""
    return f"model-{uuid4().hex}"


# ── Provider factory seam (testable) ───────────────────────────────────────


def _build_model_provider(profile: ModelProfile) -> Any:
    """Construct a concrete ModelGateway provider from a profile.

    This is a narrow factory seam for testing — automated tests replace
    this function to inject a fake ``ModelGateway`` without changing the
    production composition.

    Args:
        profile: A validated ``ModelProfile`` with ``provider == "ollama"``.

    Returns:
        An ``OllamaModelProvider`` instance.

    Raises:
        ValidationError: If the profile's provider is not supported.
    """
    if profile.provider == "ollama":
        from dnd_assistant.models.ollama import OllamaModelProvider

        return OllamaModelProvider(profile)

    raise ValidationError(
        f"Unsupported model provider '{profile.provider}'. Currently only 'ollama' is supported."
    )


# ── AskRuntime ─────────────────────────────────────────────────────────────


class AskRuntime:
    """Composed runtime for one ``dnd ask`` invocation.

    Owns the lifetime of all composed dependencies.  ``close()`` must be
    called after the command completes to release provider resources.

    Attributes:
        agent_loop: The fully wired ``AgentLoop``.
        model_gateway: The concrete ``ModelGateway`` provider.
        recovery_service: The ``SessionRecoveryService`` for preflight.
        vault_root: The resolved Vault root path.
        audit_service: The audit service (may be ``None`` for READ-only).
        execution_context: The ``ExecutionContext`` for this invocation.
    """

    def __init__(self, runtime: _RuntimeComponents) -> None:
        self._model_gateway = runtime.model_gateway
        self.agent_loop = runtime.agent_loop
        self.recovery_service = runtime.recovery_service
        self.vault_root = runtime.vault_root
        self.audit_service = runtime.audit_service
        self._execution_context: ExecutionContext | None = None

    @property
    def model_gateway(self) -> Any:
        """The concrete ModelGateway provider instance."""
        return self._model_gateway

    @property
    def execution_context(self) -> ExecutionContext:
        """The ExecutionContext for this invocation.

        Raises:
            RuntimeError: If the context has not been set (programming error).
        """
        if self._execution_context is None:
            raise RuntimeError("execution_context not set — compose_ask_runtime must set it")
        return self._execution_context

    def close(self) -> None:
        """Release provider resources.

        Safe to call multiple times — only the first call has an effect.
        """
        if self._model_gateway is not None:
            gw = self._model_gateway
            self._model_gateway = None  # type: ignore[assignment]
            gw.close()


# ── Internal component bundle ──────────────────────────────────────────────


class _RuntimeComponents:
    """Internal bundle of composed components before AskRuntime wrapping."""

    def __init__(self, **kwargs: Any) -> None:
        self.model_gateway: Any = kwargs["model_gateway"]
        self.agent_loop: AgentLoop = kwargs["agent_loop"]
        self.recovery_service: SessionRecoveryService = kwargs["recovery_service"]
        self.vault_root: Path = kwargs["vault_root"]
        self.audit_service: AuditService | None = kwargs.get("audit_service")


# ── Profile loading ────────────────────────────────────────────────────────


def _load_profile(config_path: Path, profile_name: str) -> ModelProfile:
    """Load and validate a model profile.

    Args:
        config_path: Path to the machine-local TOML config file.
        profile_name: The exact profile name to select.

    Returns:
        The validated ``ModelProfile``.

    Raises:
        DndAssistantError: If the profile is missing, has the wrong role,
            or the config is invalid.
    """
    config = load_model_profiles(config_path)

    if profile_name not in config.profiles:
        raise ValidationError(f"Profile '{profile_name}' not found in configuration")

    profile = config.profiles[profile_name]

    if profile.role is not ModelProfileRole.AGENT:
        raise ValidationError(
            f"Profile '{profile_name}' has role '{profile.role.value}', "
            f"expected '{ModelProfileRole.AGENT.value}'"
        )

    return profile


# ── Session-mode derivation ────────────────────────────────────────────────


def _derive_session_context(
    session_repository: ObsidianSessionMetadataRepository,
) -> tuple[SessionMode, str | None]:
    """Determine the current session mode and optional session ID from one trusted read.

    Uses a single ``get_active_session()`` call for both the session mode
    and the active session ID (used for audit context).

    Returns:
        A tuple of ``(SessionMode, active_session_id_or_None)``.

    Raises:
        StorageError: Propagated from the repository.
        ValidationError: Propagated from the repository.
    """
    active = session_repository.get_active_session()
    if active is not None:
        return SessionMode.ACTIVE_SESSION, active.session.id
    return SessionMode.NO_ACTIVE_SESSION, None


# ── AuditContext factory ───────────────────────────────────────────────────


def _build_ask_audit_context(
    *,
    model_profile: str,
    prompt_version: str,
    session_id: str | None = None,
) -> AuditContext:
    """Build a fresh AuditContext for a model-tool invocation.

    Args:
        model_profile: The exact CLI ``--profile`` name.
        prompt_version: The canonical prompt version identifier.
        session_id: Optional active session ID.

    Returns:
        A new ``AuditContext`` with current time, unique operation ID,
        and trace metadata.
    """
    return AuditContext(
        operation_id=_new_operation_id(),
        real_time=_now_utc(),
        source="model_tool",
        model_profile=model_profile,
        prompt_version=prompt_version,
        session=session_id,
    )


# ── 12-tool CLI registry builder ──────────────────────────────────────────


def _build_ask_tool_registry(
    *,
    search_service: VaultSearchService,
    repository: ObsidianVaultRepository,
    runtime_service: SessionRuntimeService,
    recovery_service: SessionRecoveryService,
    session_repository: ObsidianSessionMetadataRepository,
    event_repository: ObsidianSessionEventRepository,
) -> ToolRegistry:
    """Build the S9-06 production tool registry (12 tools, no calendar/world-time).

    This registry contains exactly the 12 currently composable entity and
    session tools.  The six calendar/world-time tools are deferred until a
    canonical campaign calendar-definition startup source exists.

    Returns:
        A ``ToolRegistry`` with exactly 12 registered tools.
    """
    registry = ToolRegistry()

    register_entity_read_tools(
        registry,
        search_service=search_service,
        repository=repository,
    )

    register_entity_mutation_tools(
        registry,
        search_service=search_service,
        repository=repository,
    )

    register_session_read_tools(
        registry,
        runtime_service=runtime_service,
        session_repository=session_repository,
        event_repository=event_repository,
    )

    register_session_mutation_tools(
        registry,
        runtime_service=runtime_service,
        recovery_service=recovery_service,
    )

    return registry


# ── Main composition ───────────────────────────────────────────────────────


def compose_ask_runtime(
    *,
    vault_root: Path,
    config_path: Path,
    profile_name: str,
    allow_write: bool = False,
    model_provider_factory: Any = None,
) -> AskRuntime:
    """Compose the full ``AskRuntime`` for one ``dnd ask`` invocation.

    Args:
        vault_root: The resolved Vault root path.
        config_path: Path to the machine-local TOML config file.
        profile_name: The exact model profile name to select.
        allow_write: If ``True``, grant WRITE permission and build an
            AuditContext.  Default is READ-only.
        model_provider_factory: Optional override for the model provider
            factory (used in tests to inject a fake ``ModelGateway``).
            Defaults to ``_build_model_provider``.

    Returns:
        A fully wired ``AskRuntime``.  Caller must call ``.close()`` after
        use.

    Raises:
        DndAssistantError: Profile loading, composition, or provider
            construction fails.
    """
    # 1. Load and validate profile
    profile = _load_profile(config_path, profile_name)

    # 2. Build model provider with ExitStack for deterministic cleanup
    #    before AskRuntime is returned.
    factory = model_provider_factory or _build_model_provider
    model_gateway = factory(profile)

    with ExitStack() as stack:
        stack.callback(model_gateway.close)

        # 3. Compose storage/repository layer
        audit_log_path = vault_root / "_system" / "audit" / "audit.jsonl"
        audit_service = AuditService(str(audit_log_path))

        vault_repository = ObsidianVaultRepository(
            vault_root=str(vault_root),
            audit_service=audit_service,
        )

        session_repository = ObsidianSessionMetadataRepository(vault_root, audit_service)
        event_repository = ObsidianSessionEventRepository(vault_root, audit_service)
        world_time_repository = ObsidianWorldTimeRepository(vault_root, audit_service)
        recovery_repository = ObsidianSessionRecoveryRepository(vault_root, audit_service)

        # 4. Compose application services
        runtime_service = SessionRuntimeService(
            session_repository,
            world_time_repository,
            event_repository,
        )
        recovery_service = SessionRecoveryService(recovery_repository)

        # 5. Compose retrieval
        fts_index = SqliteFtsIndex(vault_root=str(vault_root))
        search_service = VaultSearchService(
            repository=vault_repository,
            lexical_index=fts_index,
        )

        # 6. Compose tool registry (12 tools — no calendar/world-time)
        tool_registry = _build_ask_tool_registry(
            search_service=search_service,
            repository=vault_repository,
            runtime_service=runtime_service,
            recovery_service=recovery_service,
            session_repository=session_repository,
            event_repository=event_repository,
        )

        # 7. Build tool catalog and executor
        tool_catalog = build_tool_registry_schema(tool_registry)
        tool_executor = ToolExecutor(tool_registry)
        tool_execution_service = AgentToolExecutionService(tool_executor=tool_executor)

        # 8. Build context builder
        context_builder = AgentContextBuilder(
            search_service=search_service,
            vault_repository=vault_repository,
            session_repository=session_repository,
            event_repository=event_repository,
            world_time_repository=world_time_repository,
        )

        # 9. Build AgentLoop
        agent_loop = AgentLoop(
            context_builder=context_builder,
            model_gateway=model_gateway,
            tool_catalog=tool_catalog,
            tool_execution_service=tool_execution_service,
        )

        # 10. Determine session context from one trusted read.
        #     Both session mode and optional session ID come from a single
        #     ``get_active_session()`` call.
        session_mode, active_session_id = _derive_session_context(session_repository)

        if allow_write:
            from dnd_assistant.prompts.agent_v2 import PROMPT_VERSION

            audit_ctx = _build_ask_audit_context(
                model_profile=profile_name,
                prompt_version=PROMPT_VERSION,
                session_id=active_session_id,
            )
            execution_context = ExecutionContext(
                granted_permission=Permission.WRITE,
                session_mode=session_mode,
                audit=audit_ctx,
            )
        else:
            audit_ctx = None
            execution_context = ExecutionContext(
                granted_permission=Permission.READ,
                session_mode=session_mode,
                audit=None,
            )

        # 11. Store execution context on runtime for later use
        components = _RuntimeComponents(
            model_gateway=model_gateway,
            agent_loop=agent_loop,
            recovery_service=recovery_service,
            vault_root=vault_root,
            audit_service=audit_service if allow_write else None,
        )

        runtime = AskRuntime(components)
        runtime._execution_context = execution_context
        runtime._profile_name = profile_name  # type: ignore[attr-defined]

        # Transfer provider ownership to AskRuntime — ExitStack will NOT
        # close the provider on normal exit.
        stack.pop_all()

    return runtime
