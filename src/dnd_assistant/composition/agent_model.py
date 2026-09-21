"""Shared agent model/profile resolution and model lifetime (TUI-02).

This module owns the presentation-neutral primitives used by the shared agent
runtime composition (:mod:`dnd_assistant.composition.agent_runtime`):

- profile loading and AGENT-role enforcement;
- Pydantic AI ``Model`` construction via the project-owned factory;
- idempotent model cleanup;
- model-tool ``AuditContext`` identity (``source="model_tool"``).

It contains no Typer/Textual/CLI concerns.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from pydantic_ai.models import Model

from dnd_assistant.errors import ValidationError
from dnd_assistant.models.profiles import ModelProfile, ModelProfileRole, load_model_profiles
from dnd_assistant.models.pydantic_ai_deepseek import build_pydantic_ai_deepseek_model
from dnd_assistant.models.pydantic_ai_ollama import build_pydantic_ai_ollama_model
from dnd_assistant.storage.audit import AuditContext

# ── Time and ID helpers (testable via monkeypatch) ─────────────────────────


def _now_utc() -> datetime:
    """Return the current UTC time with timezone awareness."""
    return datetime.now(UTC)


def _new_operation_id() -> str:
    """Return a unique operation ID for a model-tool invocation."""
    return f"model-{uuid4().hex}"


# ── Model factory seam (testable) ──────────────────────────────────────────


def _build_agent_model(profile: ModelProfile) -> Model:
    """Construct a Pydantic AI ``Model`` from a profile.

    This is the shared, presentation-neutral provider-dispatch seam.  Provider
    selection comes exclusively from the named model profile; the concrete
    provider factory owns provider-specific validation.

    Args:
        profile: A validated ``ModelProfile`` with ``provider`` ``"ollama"``
            or ``"deepseek"``, both with ``role == AGENT``.

    Returns:
        A configured Pydantic AI ``OllamaModel`` or ``OpenAIChatModel`` instance.

    Raises:
        ValidationError: If the profile's provider is not supported, or the
            selected provider factory rejects the profile.
    """
    if profile.provider == "ollama":
        return build_pydantic_ai_ollama_model(profile)

    if profile.provider == "deepseek":
        return build_pydantic_ai_deepseek_model(profile)

    raise ValidationError(
        f"Unsupported model provider {profile.provider!r} for the AGENT role. "
        f"Supported providers: 'deepseek', 'ollama'."
    )


def _close_model(model: Model) -> None:
    """Release model resources if the concrete model exposes a close hook.

    Pydantic AI's ``OllamaModel`` has no project-owned synchronous close
    contract, so this is normally a no-op.  It still releases test-injected
    models that expose ``close()`` and keeps composition-failure cleanup
    observable.
    """
    close = getattr(model, "close", None)
    if callable(close):
        close()


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
