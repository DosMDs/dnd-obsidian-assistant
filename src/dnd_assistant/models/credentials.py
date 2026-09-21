"""Machine-local provider credential resolution.

Architectural boundary
──────────────────────
Provider credentials are machine-local secrets.  This module owns the narrow
lookup contract between a provider identity and the environment variable that
holds its credential.

It deliberately does **not** read configuration files, and the profile loader
(:mod:`dnd_assistant.models.profiles`) never reads the environment.  Credential
resolution happens only when a provider transport is actually constructed, at
a separate machine-local boundary from profile parsing.

Rules:

- the provider → environment-variable mapping is fixed here;
- an unknown provider performs no environment lookup and fails closed;
- a missing, empty or whitespace-only credential fails closed;
- the resolved credential is returned as :class:`pydantic.SecretStr`, whose
  ``repr``/``str`` never reveal the value;
- error text never contains the secret value;
- credentials are never stored in a profile, the Vault, reports, traces or
  any persisted evidence.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from typing import Final

from pydantic import SecretStr

from dnd_assistant.errors import CredentialError, ValidationError

DEEPSEEK_API_KEY_ENV: Final[str] = "DEEPSEEK_API_KEY"

PROVIDER_API_KEY_ENV: Final[Mapping[str, str]] = {
    "deepseek": DEEPSEEK_API_KEY_ENV,
}


def provider_credential_env_var(provider: str) -> str:
    """Return the machine-local environment variable name for ``provider``.

    Raises:
        ValidationError: The provider has no defined credential mapping.  No
            environment lookup is performed for an unknown provider.
    """
    try:
        return PROVIDER_API_KEY_ENV[provider]
    except KeyError:
        raise ValidationError(
            f"No machine-local credential is defined for provider {provider!r}"
        ) from None


def resolve_provider_api_key(provider: str) -> SecretStr:
    """Resolve the machine-local API key for ``provider``.

    The value is read from the provider's environment variable at call time
    and returned as a :class:`pydantic.SecretStr`; the raw value is exposed
    only through :meth:`pydantic.SecretStr.get_secret_value`.

    Raises:
        ValidationError: The provider has no defined credential mapping.
        CredentialError: The credential is missing, empty or whitespace-only.
    """
    env_var = provider_credential_env_var(provider)

    raw = os.environ.get(env_var)
    if raw is None or not raw.strip():
        raise CredentialError(
            "Missing or empty machine-local credential for provider "
            f"{provider!r} (environment variable {env_var})"
        )

    return SecretStr(raw)
