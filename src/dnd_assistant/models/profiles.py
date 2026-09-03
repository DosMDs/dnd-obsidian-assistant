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

from pydantic import BaseModel, field_validator

from dnd_assistant.errors import NotFoundError, StorageError, ValidationError

# ── Role enum ─────────────────────────────────────────────────────────────


class ModelProfileRole(StrEnum):
    """Canonical MVP roles for model profiles.

    These represent the functional role a model plays in the application.
    Concrete model names are determined by configuration, not by this enum.
    """

    AGENT = "agent"
    SUMMARIZER = "summarizer"
    EMBEDDING = "embedding"


# ── HTTP/HTTPS URL validation ─────────────────────────────────────────────


def _validate_http_url(value: str) -> str:
    """Validate that a string is a plausible HTTP/HTTPS URL.

    No DNS resolution or network access is performed.
    """
    if not value.startswith(("http://", "https://")):
        raise ValueError(f"base_url must start with http:// or https://, got {value!r}")
    rest = value.split("://", 1)[1]
    if not rest:
        raise ValueError(f"base_url has no host after scheme: {value!r}")
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
