"""Machine-local settings boundary (CFG-00).

Ownership
─────────
This module owns the single typed boundary for machine-local (per-installation)
settings:

- the project-owned ``.env`` discovery/``DND_ENV_FILE`` bootstrap selector;
- the typed machine-settings schema (:class:`MachineSettings`);
- the absolute-path semantics for the machine-local model-config path and the
  machine-local Vault path;
- the machine-local provider-credential mapping and fail-closed resolution.

It deliberately does **not**:

- validate or parse the model-profile TOML file — ``models.profiles``
  ``load_model_profiles`` remains the sole owner of file existence/read/TOML/
  profile validation errors; the settings layer never checks file existence,
  reads the file or inspects its ``[profiles.*]`` content;
- validate the Vault itself — ``vault_path`` is only a machine-local **pointer**
  to the campaign Vault.  Existence, directory layout, campaign structure and
  storage validity remain owned by the Vault/application/storage boundaries
  (for example ``storage.paths._resolve_vault_root``); the settings layer never
  checks Vault existence or contents;
- read campaign/Vault configuration;
- import any concrete model provider or presentation framework.

Source precedence
─────────────────
:class:`MachineSettings` preserves, in order:

    explicit construction arguments  (tests / explicit overrides)
        > real process environment
        > the selected machine-local dotenv file
        > safe defaults

``DND_ENV_FILE`` is a **bootstrap selector only**: it is read exclusively from
the real process environment, must be an absolute path when set, and can never
be redirected by the dotenv file itself (it is not a settings field and is
rejected as an unknown key by the dedicated dotenv, which uses
``extra="forbid"``).

The dedicated dotenv uses ``extra="forbid"`` with ``hide_input_in_errors=True``
so an unknown/typo key fails fast **without** echoing the (possibly secret)
value.  Unrelated process environment variables are never rejected: only
declared fields are read from the environment.
"""

from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Final

from pydantic import Field, SecretStr, field_validator
from pydantic import ValidationError as PydanticValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict

from dnd_assistant.errors import CredentialError, ValidationError

# ── Canonical external names ──────────────────────────────────────────────
#
# Project-owned machine settings use the ``DND_`` prefix.  The provider
# credential keeps its accepted provider-standard name (no prefix).

MACHINE_ENV_FILE_ENV: Final[str] = "DND_ENV_FILE"
MODEL_CONFIG_PATH_ENV: Final[str] = "DND_MODEL_CONFIG_PATH"
VAULT_PATH_ENV: Final[str] = "DND_VAULT_PATH"
DEEPSEEK_API_KEY_ENV: Final[str] = "DEEPSEEK_API_KEY"

PROVIDER_API_KEY_ENV: Final[Mapping[str, str]] = {
    "deepseek": DEEPSEEK_API_KEY_ENV,
}

_ENV_PREFIX: Final[str] = "DND_"
_DOTENV_FILENAME: Final[str] = ".env"
_PROJECT_MARKER: Final[str] = "pyproject.toml"
_PROJECT_NAME: Final[str] = "dnd-assistant"


# ── Dotenv discovery / bootstrap selector ─────────────────────────────────


def _find_project_root(start: Path) -> Path | None:
    """Return the nearest enclosing D&D Assistant project root at/above ``start``.

    A directory qualifies as the project root only when it contains a
    ``pyproject.toml`` that parses and declares ``[project].name ==
    "dnd-assistant"``.  Malformed, unreadable or non-matching markers are
    skipped, so an unrelated parent ``pyproject.toml``/``.env`` is never
    selected.

    Returns:
        The qualifying project root, or ``None`` when none is found.
    """
    for candidate in (start, *start.parents):
        marker = candidate / _PROJECT_MARKER
        if not marker.is_file():
            continue
        try:
            data = tomllib.loads(marker.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            continue
        project = data.get("project")
        if isinstance(project, dict) and project.get("name") == _PROJECT_NAME:
            return candidate
    return None


def _project_root() -> Path:
    """Resolve the D&D Assistant project root from the invocation context.

    Resolution starts at the current working directory and walks upward; see
    :func:`_find_project_root`.  It never falls back to the installed package
    location, the user home directory, a user configuration directory or an
    unrelated parent directory.

    Raises:
        ValidationError: No enclosing D&D Assistant project root was found.
    """
    try:
        start = Path.cwd().resolve()
    except OSError as exc:  # pragma: no cover - deleted/inaccessible CWD
        raise ValidationError(
            "Could not determine the current working directory to locate the "
            f"D&D Assistant project root: {exc}. Set {MACHINE_ENV_FILE_ENV} to an "
            "absolute dotenv path to bypass project-root discovery."
        ) from None
    root = _find_project_root(start)
    if root is None:
        raise ValidationError(
            "No D&D Assistant project root could be found from the current working "
            f"directory ({start}); no enclosing {_PROJECT_MARKER} declares "
            f"[project].name = {_PROJECT_NAME!r}. Run from inside the project or set "
            f"{MACHINE_ENV_FILE_ENV} to an absolute dotenv path."
        )
    return root


def machine_env_file() -> Path:
    """Resolve the machine-local dotenv path.

    ``DND_ENV_FILE`` is a bootstrap selector: it is read only from the real
    process environment (never from the dotenv file), must be an absolute path
    when provided, and cannot redirect itself.  When it is unset, the default is
    the ``.env`` at the nearest enclosing D&D Assistant project root discovered
    from the current working directory (see :func:`_project_root`); an invocation
    outside a project checkout must set ``DND_ENV_FILE`` to opt into dotenv
    loading.

    Returns:
        The selected dotenv path.

    Raises:
        ValidationError: ``DND_ENV_FILE`` is set but not an absolute path, or no
            enclosing project root can be found.
    """
    raw = os.environ.get(MACHINE_ENV_FILE_ENV)
    if raw is not None and raw.strip():
        selected = Path(raw.strip())
        if not selected.is_absolute():
            raise ValidationError(f"{MACHINE_ENV_FILE_ENV} must be an absolute path, got {raw!r}")
        return selected
    return _project_root() / _DOTENV_FILENAME


# ── Credential mapping / fail-closed resolution ───────────────────────────


def provider_credential_env_var(provider: str) -> str:
    """Return the machine-local environment variable name for ``provider``.

    Raises:
        ValidationError: The provider has no defined credential mapping.  No
            environment or file lookup is performed for an unknown provider.
    """
    try:
        return PROVIDER_API_KEY_ENV[provider]
    except KeyError:
        raise ValidationError(
            f"No machine-local credential is defined for provider {provider!r}"
        ) from None


def require_provider_api_key(provider: str, value: SecretStr | None) -> SecretStr:
    """Fail closed unless ``value`` is a non-empty provider credential.

    This is the single fail-closed credential check.  It performs no
    environment or file access: the value must already come from the typed
    settings boundary (or an explicit override).  Error text never contains the
    secret value.

    Raises:
        ValidationError: The provider has no defined credential mapping.
        CredentialError: The credential is missing, empty or whitespace-only.
    """
    env_var = provider_credential_env_var(provider)
    if value is None or not value.get_secret_value().strip():
        raise CredentialError(
            "Missing or empty machine-local credential for provider "
            f"{provider!r} (environment variable {env_var})"
        )
    return value


# ── Typed machine settings ────────────────────────────────────────────────


class MachineSettings(BaseSettings):
    """Typed machine-local settings.

    Direct construction reads the real process environment only (used by
    explicit/isolated callers and tests).  Production entry points build the
    object through :func:`load_machine_settings`, which additionally selects
    the machine-local dotenv file.

    ``model_config_path`` and ``vault_path`` carry absolute-path semantics only;
    the model-profile TOML file's existence/content is owned by
    ``load_model_profiles`` and the Vault's existence/layout is owned by the
    Vault/application/storage boundaries.
    """

    model_config = SettingsConfigDict(
        env_prefix=_ENV_PREFIX,
        env_file_encoding="utf-8",
        extra="forbid",
        hide_input_in_errors=True,
        case_sensitive=False,
        env_ignore_empty=True,
        populate_by_name=True,
        frozen=True,
    )

    model_config_path: Path | None = None
    vault_path: Path | None = None
    deepseek_api_key: SecretStr | None = Field(
        default=None,
        validation_alias=DEEPSEEK_API_KEY_ENV,
    )

    @field_validator("model_config_path")
    @classmethod
    def _require_absolute_model_config_path(cls, value: Path | None) -> Path | None:
        if value is not None and not value.is_absolute():
            raise ValueError("model_config_path must be an absolute path")
        return value

    @field_validator("vault_path")
    @classmethod
    def _require_absolute_vault_path(cls, value: Path | None) -> Path | None:
        if value is not None and not value.is_absolute():
            raise ValueError("vault_path must be an absolute path")
        return value

    def provider_api_key(self, provider: str) -> SecretStr:
        """Return the fail-closed machine-local credential for ``provider``.

        Raises:
            ValidationError: The provider has no defined credential mapping.
            CredentialError: The credential is missing, empty or whitespace-only.
        """
        # ``provider_credential_env_var`` validates the provider first, keeping
        # the provider → external-name mapping a single source of truth.
        provider_credential_env_var(provider)
        return require_provider_api_key(provider, self._provider_api_key_value(provider))

    def _provider_api_key_value(self, provider: str) -> SecretStr | None:
        # Provider → typed-field mapping.  Still a single provider today; the
        # external-name mapping above stays the validating source of truth.
        if provider == "deepseek":
            return self.deepseek_api_key
        return None


def load_machine_settings(*, env_file: Path | None = None) -> MachineSettings:
    """Build :class:`MachineSettings` from the machine dotenv and process env.

    Args:
        env_file: Explicit dotenv source (isolated callers/tests).  When
            ``None``, the machine-local path from :func:`machine_env_file` is
            used.

    Returns:
        Validated, frozen machine settings.

    Raises:
        ValidationError: The bootstrap selector is not absolute, or the settings
            fail validation (bad type/unknown dedicated-dotenv key).  Error text
            is sanitized: it never contains setting values.
    """
    resolved = env_file if env_file is not None else machine_env_file()
    # ``_env_file`` is a pydantic-settings runtime keyword; passing it through a
    # mapping keeps the call compatible with Pydantic's ``dataclass_transform``
    # view of ``BaseSettings.__init__`` (which only exposes field names).
    options: dict[str, Any] = {"_env_file": resolved}
    try:
        return MachineSettings(**options)
    except PydanticValidationError as exc:
        # ``hide_input_in_errors`` already redacts values; re-raise as a project
        # error with no chained cause so a raw settings traceback never escapes.
        raise ValidationError(str(exc)) from None


def resolve_model_config_path(explicit: Path | None, settings: MachineSettings) -> Path:
    """Resolve the model-config path: explicit override > settings value.

    This performs no file existence/read/TOML validation; that remains owned by
    ``dnd_assistant.models.profiles.load_model_profiles``.

    Raises:
        ValidationError: Neither an explicit path nor a machine-local
            ``model_config_path`` is available.
    """
    path = explicit if explicit is not None else settings.model_config_path
    if path is None:
        raise ValidationError(
            "Machine-local model configuration path is not set. "
            f"Pass --config or set {MODEL_CONFIG_PATH_ENV}."
        )
    return path


def load_model_config_path(explicit: Path | None) -> Path:
    """Load machine settings and resolve the model-config path.

    Convenience for entry points that need only the resolved path (no provider
    credential).
    """
    return resolve_model_config_path(explicit, load_machine_settings())


def resolve_vault_path(explicit: Path | None, settings: MachineSettings) -> Path:
    """Resolve the Vault path: explicit ``--vault`` > machine-local setting.

    ``vault_path`` is only a machine-local pointer to the campaign Vault.  This
    performs no Vault existence/directory/layout validation; that remains owned
    by the Vault/application/storage boundaries.

    Raises:
        ValidationError: Neither an explicit path nor a machine-local
            ``vault_path`` is available.
    """
    path = explicit if explicit is not None else settings.vault_path
    if path is None:
        raise ValidationError(
            f"Machine-local Vault path is not set. Pass --vault or set {VAULT_PATH_ENV}."
        )
    return path
