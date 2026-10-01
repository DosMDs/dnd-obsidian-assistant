"""Machine-local configuration boundary (CFG-00).

This package owns the single typed boundary for machine-local settings,
dotenv discovery and provider-credential resolution.  It is deliberately
separate from campaign/Vault configuration (``domain``/``storage``) and from
concrete provider implementation (``models``); it contains no model-provider or
presentation logic.
"""

from dnd_assistant.config.settings import (
    DEEPSEEK_API_KEY_ENV,
    MACHINE_ENV_FILE_ENV,
    MODEL_CONFIG_PATH_ENV,
    PROVIDER_API_KEY_ENV,
    MachineSettings,
    load_machine_settings,
    load_model_config_path,
    machine_env_file,
    provider_credential_env_var,
    require_provider_api_key,
    resolve_model_config_path,
)

__all__ = [
    "DEEPSEEK_API_KEY_ENV",
    "MACHINE_ENV_FILE_ENV",
    "MODEL_CONFIG_PATH_ENV",
    "PROVIDER_API_KEY_ENV",
    "MachineSettings",
    "load_machine_settings",
    "load_model_config_path",
    "machine_env_file",
    "provider_credential_env_var",
    "require_provider_api_key",
    "resolve_model_config_path",
]
