"""Machine-local model profile configuration.

This module defines typed schemas for runtime model profiles and a
deterministic TOML loader for the machine-local configuration file.

Architectural boundary
─────────────────────
Machine configuration lives outside the Vault.  It contains model/runtime
settings for the local machine and must never be stored in or derived
from campaign data.

Model selection is configuration, not architecture.  Concrete model names
must never be hardcoded into application or domain behaviour.

S8-01 owns only the ``profiles`` subsection of the machine-local TOML.
Unrelated top-level sections (e.g. ``[timeouts]``, ``[cache]``) are
intentionally left outside this module's model.
"""

from __future__ import annotations

import math
import tomllib
from enum import StrEnum
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, field_validator, model_validator

from dnd_assistant.errors import NotFoundError, StorageError, ValidationError

# ── Canonical provider identifiers ────────────────────────────────────────
#
# Provider identity remains an open string so configuration representability
# stays independent of production provider support.  ``_DEEPSEEK_PROVIDER``
# names the only provider for which provider-specific reasoning settings are
# currently validated; unsupported providers still fail closed at the
# model-construction boundary.

_DEEPSEEK_PROVIDER = "deepseek"


# ── Role enum ─────────────────────────────────────────────────────────────


class ModelProfileRole(StrEnum):
    """Canonical MVP roles for model profiles.

    These represent the functional role a model plays in the application.
    Concrete model names are determined by configuration, not by this enum.
    """

    AGENT = "agent"
    SUMMARIZER = "summarizer"
    EMBEDDING = "embedding"
    POST_SESSION = "post_session"
    BOOTSTRAP = "bootstrap"


# ── Reasoning effort enum ─────────────────────────────────────────────────


class ReasoningEffort(StrEnum):
    """Canonical project reasoning-effort vocabulary.

    Only ``low``, ``high`` and ``max`` are canonical project values.  Provider
    compatibility aliases (for example ``medium``) are deliberately not
    members; they must not become implicit project values.
    """

    LOW = "low"
    HIGH = "high"
    MAX = "max"


# ── HTTP/HTTPS URL validation ─────────────────────────────────────────────


def _validate_http_url(value: str) -> str:
    """Validate that a string is a syntactically valid HTTP/HTTPS URL.

    Uses the standard-library URL parser (``urlsplit``) to verify:
    1. scheme is exactly ``http`` or ``https``.
    2. network location (netloc) is structurally present.
    3. a non-empty, non-whitespace hostname exists.
    4. when a port is provided, it is a valid integer.

    No DNS resolution, HTTP request, or socket connection is performed.
    """
    if not value.startswith(("http://", "https://")):
        raise ValueError(f"base_url must start with http:// or https://, got {value!r}")

    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise ValueError(f"base_url is not a valid URL: {value!r}") from exc

    if not parsed.netloc:
        raise ValueError(f"base_url has no network location (host): {value!r}")

    hostname = parsed.hostname
    if not hostname or not hostname.strip():
        raise ValueError(f"base_url has no usable hostname: {value!r}")

    # Accessing .port on a malformed port raises ValueError
    try:
        _ = parsed.port  # noqa: F841 — validate port syntax
    except ValueError as exc:
        raise ValueError(f"base_url has an invalid port: {value!r}") from exc

    return value


# ── Individual model profile ──────────────────────────────────────────────


class ModelProfile(BaseModel):
    """A single configured model profile.

    Each profile describes one model instance the application may use,
    including its provider, endpoint, and runtime parameters.
    """

    provider: str
    model: str
    base_url: str
    temperature: float | None = None
    keep_alive: str | None = None
    role: ModelProfileRole
    thinking: bool | None = None
    reasoning_effort: ReasoningEffort | None = None

    model_config = {"extra": "forbid", "frozen": True}

    # ── provider ──────────────────────────────────────────────────────

    @field_validator("provider")
    @classmethod
    def _provider_non_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("provider must be non-empty and not whitespace-only")
        return stripped

    # ── model ─────────────────────────────────────────────────────────

    @field_validator("model")
    @classmethod
    def _model_non_empty(cls, v: str) -> str:
        stripped = v.strip()
        if not stripped:
            raise ValueError("model must be non-empty and not whitespace-only")
        return stripped

    # ── base_url ──────────────────────────────────────────────────────

    @field_validator("base_url")
    @classmethod
    def _validate_base_url(cls, v: str) -> str:
        return _validate_http_url(v)

    # ── temperature ───────────────────────────────────────────────────

    @field_validator("temperature")
    @classmethod
    def _validate_temperature(cls, v: float | None) -> float | None:
        if v is not None:
            if math.isnan(v):
                raise ValueError("temperature must not be NaN")
            if math.isinf(v):
                raise ValueError("temperature must not be Infinity")
            if v < 0:
                raise ValueError("temperature must not be negative")
        return v

    # ── keep_alive ────────────────────────────────────────────────────

    @field_validator("keep_alive")
    @classmethod
    def _keep_alive_non_empty(cls, v: str | None) -> str | None:
        if v is not None:
            stripped = v.strip()
            if not stripped:
                raise ValueError("keep_alive must not be empty or whitespace-only")
            return stripped
        return None

    # ── thinking / reasoning_effort (provider- and role-gated) ─────────

    @model_validator(mode="after")
    def _validate_reasoning_settings(self) -> ModelProfile:
        """Enforce the accepted DeepSeek AGENT reasoning contract.

        Reasoning settings are representable only for the canonical DeepSeek
        provider and, in this release, only for the ``agent`` role.  For a
        DeepSeek agent profile ``thinking`` must be explicit: no profile may
        fall through to implicit provider/framework thinking defaults.
        """
        has_reasoning = self.thinking is not None or self.reasoning_effort is not None

        if self.provider != _DEEPSEEK_PROVIDER:
            if has_reasoning:
                raise ValueError(
                    "thinking/reasoning_effort are only supported for provider "
                    f"{_DEEPSEEK_PROVIDER!r}, got provider {self.provider!r}"
                )
            return self

        if self.role is not ModelProfileRole.AGENT:
            if has_reasoning:
                raise ValueError(
                    "thinking/reasoning_effort are only supported for role "
                    f"{ModelProfileRole.AGENT.value!r} in this release, "
                    f"got role {self.role.value!r}"
                )
            return self

        if self.thinking is None:
            raise ValueError(
                "provider 'deepseek' agent profile must set thinking explicitly "
                "(true or false); implicit provider thinking defaults are not allowed"
            )
        if self.thinking and self.reasoning_effort is None:
            effort_values = "|".join(effort.value for effort in ReasoningEffort)
            raise ValueError(
                f"thinking=true requires an explicit reasoning_effort ({effort_values})"
            )
        if not self.thinking and self.reasoning_effort is not None:
            raise ValueError("thinking=false must not set reasoning_effort")
        return self


# ── Profile collection ────────────────────────────────────────────────────


class ModelProfilesConfig(BaseModel):
    """Typed collection of named model profiles.

    At least one profile must exist.  Profile names must be non-empty and
    not whitespace-only.  No profile is implicitly selected as a global
    default in S8-01.
    """

    profiles: dict[str, ModelProfile]

    model_config = {"extra": "forbid", "frozen": True}

    @field_validator("profiles")
    @classmethod
    def _at_least_one_profile(cls, v: dict[str, ModelProfile]) -> dict[str, ModelProfile]:
        if not v:
            raise ValueError("at least one profile is required")
        for name in v:
            stripped = name.strip()
            if not stripped:
                raise ValueError("profile name must not be empty or whitespace-only")
        return v


# ── TOML loader ───────────────────────────────────────────────────────────


def load_model_profiles(path: Path) -> ModelProfilesConfig:
    """Load model profiles from a machine-local TOML file.

    The TOML file may contain other top-level sections (e.g. ``[timeouts]``,
    ``[cache]``) — those are intentionally ignored.  Only the ``[profiles.*]``
    subsection is validated into the typed profile collection.

    Args:
        path: Absolute or relative path to the TOML configuration file.

    Returns:
        A ``ModelProfilesConfig`` containing all valid profiles.

    Raises:
        NotFoundError: The file does not exist.
        StorageError: The file exists but could not be read.
        ValidationError: The TOML content is malformed, the ``profiles``
            section is missing or invalid, or an individual profile fails
            schema validation.
    """
    if not path.exists():
        raise NotFoundError(
            f"Machine configuration file not found: {path}",
            cause=FileNotFoundError(str(path)),
        )

    try:
        raw: dict[str, Any] = tomllib.loads(path.read_text(encoding="utf-8"))
    except tomllib.TOMLDecodeError as exc:
        raise ValidationError(
            f"Failed to parse machine configuration TOML: {exc}",
            cause=exc,
        ) from exc
    except OSError as exc:
        raise StorageError(
            f"Failed to read machine configuration file: {exc}",
            cause=exc,
        ) from exc

    profiles_raw = raw.get("profiles")
    if profiles_raw is None:
        raise ValidationError("Machine configuration is missing the required 'profiles' section")
    if not isinstance(profiles_raw, dict):
        raise ValidationError(
            f"Expected 'profiles' to be a table/object, got {type(profiles_raw).__name__}"
        )

    try:
        return ModelProfilesConfig(profiles=profiles_raw)
    except Exception as exc:
        raise ValidationError(
            f"Invalid model profile configuration: {exc}",
            cause=exc,
        ) from exc
