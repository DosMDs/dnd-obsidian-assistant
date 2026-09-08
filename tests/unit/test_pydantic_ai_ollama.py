"""PAIM-09: Pydantic AI Ollama model builder — unit tests.

All tests are deterministic and require no real Ollama or network access.
"""

from __future__ import annotations

import subprocess
import sys

import pytest
from pydantic_ai.models.ollama import OllamaModel

from dnd_assistant.errors import ValidationError
from dnd_assistant.models.profiles import ModelProfile, ModelProfileRole
from dnd_assistant.models.pydantic_ai_ollama import (
    _normalize_openai_compatible_base_url,
    build_pydantic_ai_ollama_model,
)

# ==============================================================================
# Helper
# ==============================================================================


def _make_profile(
    *,
    provider: str = "ollama",
    model: str = "qwen3",
    base_url: str = "http://localhost:11434",
    temperature: float | None = None,
    keep_alive: str | None = None,
    role: ModelProfileRole = ModelProfileRole.AGENT,
) -> ModelProfile:
    """Build a ``ModelProfile`` with minimal boilerplate."""
    return ModelProfile(
        provider=provider,
        model=model,
        base_url=base_url,
        temperature=temperature,
        keep_alive=keep_alive,
        role=role,
    )


# ==============================================================================
# P9-U01 — exact OllamaModel returned
# ==============================================================================


def test_p9_u01_exact_ollama_model_returned() -> None:
    """Builder returns an ``OllamaModel`` instance."""
    profile = _make_profile()
    model = build_pydantic_ai_ollama_model(profile)
    assert type(model) is OllamaModel, f"expected OllamaModel, got {type(model).__name__}"


# ==============================================================================
# P9-U02 — model name preserved
# ==============================================================================


def test_p9_u02_model_name_preserved() -> None:
    """``model.model_name`` matches the profile's model name."""
    profile = _make_profile(model="llama3.2")
    model = build_pydantic_ai_ollama_model(profile)
    assert model.model_name == "llama3.2"


# ==============================================================================
# P9-U03 — provider/system is ollama
# ==============================================================================


def test_p9_u03_provider_system_is_ollama() -> None:
    """``model.system`` returns ``"ollama"``."""
    profile = _make_profile()
    model = build_pydantic_ai_ollama_model(profile)
    assert model.system == "ollama", f"expected 'ollama', got {model.system!r}"


# ==============================================================================
# P9-U04 — root base URL → /v1
# ==============================================================================


def test_p9_u04_root_base_url_to_v1() -> None:
    """``http://localhost:11434`` normalises to a URL ending in ``/v1/``."""
    profile = _make_profile(base_url="http://localhost:11434")
    model = build_pydantic_ai_ollama_model(profile)
    base = str(model.base_url)
    # OllamaProvider appends a trailing slash to the base URL
    assert base == "http://localhost:11434/v1/", f"got {base!r}"


# ==============================================================================
# P9-U05 — trailing slash normalisation
# ==============================================================================


def test_p9_u05_trailing_slash_normalisation() -> None:
    """``http://localhost:11434/`` normalises to a URL ending in ``/v1/``."""
    profile = _make_profile(base_url="http://localhost:11434/")
    model = build_pydantic_ai_ollama_model(profile)
    base = str(model.base_url)
    assert base == "http://localhost:11434/v1/", f"got {base!r}"


# ==============================================================================
# P9-U06 — existing /v1 not duplicated
# ==============================================================================


def test_p9_u06_existing_v1_not_duplicated() -> None:
    """``http://localhost:11434/v1`` stays a URL ending in ``/v1/``."""
    profile = _make_profile(base_url="http://localhost:11434/v1")
    model = build_pydantic_ai_ollama_model(profile)
    base = str(model.base_url)
    assert base == "http://localhost:11434/v1/", f"got {base!r}"


def test_p9_u06_existing_v1_trailing_slash_not_duplicated() -> None:
    """``http://localhost:11434/v1/`` stays ``http://localhost:11434/v1/``."""
    profile = _make_profile(base_url="http://localhost:11434/v1/")
    model = build_pydantic_ai_ollama_model(profile)
    base = str(model.base_url)
    assert base == "http://localhost:11434/v1/", f"got {base!r}"


# ==============================================================================
# P9-U07 — reverse-proxy path prefix preserved
# ==============================================================================


def test_p9_u07_reverse_proxy_path_prefix_preserved() -> None:
    """``https://example.test/ollama`` → ``https://example.test/ollama/v1/``."""
    profile = _make_profile(base_url="https://example.test/ollama")
    model = build_pydantic_ai_ollama_model(profile)
    base = str(model.base_url)
    assert base == "https://example.test/ollama/v1/", f"got {base!r}"


def test_p9_u07_reverse_proxy_trailing_slash() -> None:
    """``https://example.test/ollama/`` → ``https://example.test/ollama/v1/``."""
    profile = _make_profile(base_url="https://example.test/ollama/")
    model = build_pydantic_ai_ollama_model(profile)
    base = str(model.base_url)
    assert base == "https://example.test/ollama/v1/", f"got {base!r}"


def test_p9_u07_reverse_proxy_existing_v1() -> None:
    """``https://example.test/ollama/v1`` stays ``https://example.test/ollama/v1/``."""
    profile = _make_profile(base_url="https://example.test/ollama/v1")
    model = build_pydantic_ai_ollama_model(profile)
    base = str(model.base_url)
    assert base == "https://example.test/ollama/v1/", f"got {base!r}"


# ==============================================================================
# P9-U08 — wrong provider rejected
# ==============================================================================


def test_p9_u08_wrong_provider_rejected() -> None:
    """Non-ollama provider raises ``ValidationError``."""
    profile = _make_profile(provider="openai")
    with pytest.raises(ValidationError, match="provider='ollama'"):
        build_pydantic_ai_ollama_model(profile)


# ==============================================================================
# P9-U09 — SUMMARIZER role rejected
# ==============================================================================


def test_p9_u09_summarizer_role_rejected() -> None:
    """``SUMMARIZER`` role raises ``ValidationError``."""
    profile = _make_profile(role=ModelProfileRole.SUMMARIZER)
    with pytest.raises(ValidationError, match="role=AGENT"):
        build_pydantic_ai_ollama_model(profile)


# ==============================================================================
# P9-U10 — EMBEDDING role rejected
# ==============================================================================


def test_p9_u10_embedding_role_rejected() -> None:
    """``EMBEDDING`` role raises ``ValidationError``."""
    profile = _make_profile(role=ModelProfileRole.EMBEDDING)
    with pytest.raises(ValidationError, match="role=AGENT"):
        build_pydantic_ai_ollama_model(profile)


# ==============================================================================
# P9-U11 — keep_alive None accepted
# ==============================================================================


def test_p9_u11_keep_alive_none_accepted() -> None:
    """``keep_alive=None`` is accepted."""
    profile = _make_profile(keep_alive=None)
    model = build_pydantic_ai_ollama_model(profile)
    assert type(model) is OllamaModel


# ==============================================================================
# P9-U12 — keep_alive non-null rejected
# ==============================================================================


def test_p9_u12_keep_alive_non_null_rejected() -> None:
    """Non-null ``keep_alive`` raises ``ValidationError``."""
    profile = _make_profile(keep_alive="5m")
    with pytest.raises(ValidationError, match="keep_alive"):
        build_pydantic_ai_ollama_model(profile)


# ==============================================================================
# P9-U13 — temperature propagated
# ==============================================================================


def test_p9_u13_temperature_propagated() -> None:
    """``temperature=0.25`` is propagated to model settings dict."""
    profile = _make_profile(temperature=0.25)
    model = build_pydantic_ai_ollama_model(profile)
    assert model.settings is not None
    assert model.settings.get("temperature") == 0.25, (
        f"expected temperature=0.25, got {model.settings}"
    )


# ==============================================================================
# P9-U14 — temperature None not forced
# ==============================================================================


def test_p9_u14_temperature_none_not_forced() -> None:
    """``temperature=None`` results in empty settings (no forced default)."""
    profile = _make_profile(temperature=None)
    model = build_pydantic_ai_ollama_model(profile)
    # When no settings are provided, model.settings should be empty
    assert not model.settings, f"expected empty settings, got {model.settings}"


# ==============================================================================
# P9-U15 — builder performs zero HTTP requests
# ==============================================================================


def test_p9_u15_builder_performs_zero_http_requests() -> None:
    """Builder construction succeeds against a non-existent host without HTTP."""
    profile = _make_profile(base_url="http://nonexistent-host.invalid:9999")
    model = build_pydantic_ai_ollama_model(profile)
    assert type(model) is OllamaModel


# ==============================================================================
# P9-U16 — original ModelProfile remains unchanged
# ==============================================================================


def test_p9_u16_original_profile_unchanged() -> None:
    """Builder does not mutate the original frozen ``ModelProfile``."""
    profile = _make_profile(
        model="test-model",
        base_url="http://localhost:11434",
        temperature=0.5,
    )
    original_repr = repr(profile)
    _ = build_pydantic_ai_ollama_model(profile)
    assert repr(profile) == original_repr, "ModelProfile was mutated"


# ==============================================================================
# Malformed runtime type tests
# ==============================================================================


def test_non_model_profile_rejected() -> None:
    """Passing ``object()`` as profile raises ``ValidationError``."""
    with pytest.raises(ValidationError, match="ModelProfile"):
        build_pydantic_ai_ollama_model(object())  # type: ignore[arg-type]


def test_dict_as_profile_rejected() -> None:
    """Passing a plain dict as profile raises ``ValidationError``."""
    with pytest.raises(ValidationError, match="ModelProfile"):
        build_pydantic_ai_ollama_model({"provider": "ollama"})  # type: ignore[arg-type]


def test_duck_fake_profile_rejected() -> None:
    """Passing a duck-typed fake as profile raises ``ValidationError``."""

    class _FakeProfile:
        provider = "ollama"
        model = "qwen3"
        base_url = "http://localhost:11434"
        role = ModelProfileRole.AGENT
        keep_alive = None
        temperature = None

    with pytest.raises(ValidationError, match="ModelProfile"):
        build_pydantic_ai_ollama_model(_FakeProfile())  # type: ignore[arg-type]


# ==============================================================================
# _normalize_openai_compatible_base_url — direct unit tests
# ==============================================================================


class TestNormalizeBaseUrl:
    """Direct tests for the private URL normalisation helper."""

    def test_root_no_slash(self) -> None:
        assert _normalize_openai_compatible_base_url("http://localhost:11434") == (
            "http://localhost:11434/v1"
        )

    def test_root_trailing_slash(self) -> None:
        assert _normalize_openai_compatible_base_url("http://localhost:11434/") == (
            "http://localhost:11434/v1"
        )

    def test_already_v1(self) -> None:
        assert _normalize_openai_compatible_base_url("http://localhost:11434/v1") == (
            "http://localhost:11434/v1"
        )

    def test_already_v1_trailing_slash(self) -> None:
        assert _normalize_openai_compatible_base_url("http://localhost:11434/v1/") == (
            "http://localhost:11434/v1"
        )

    def test_reverse_proxy_prefix(self) -> None:
        assert _normalize_openai_compatible_base_url("https://example.test/ollama") == (
            "https://example.test/ollama/v1"
        )

    def test_reverse_proxy_trailing_slash(self) -> None:
        assert _normalize_openai_compatible_base_url("https://example.test/ollama/") == (
            "https://example.test/ollama/v1"
        )

    def test_reverse_proxy_already_v1(self) -> None:
        assert _normalize_openai_compatible_base_url("https://example.test/ollama/v1") == (
            "https://example.test/ollama/v1"
        )

    def test_https_scheme(self) -> None:
        assert _normalize_openai_compatible_base_url("https://remote.server:443") == (
            "https://remote.server:443/v1"
        )

    def test_custom_port(self) -> None:
        assert _normalize_openai_compatible_base_url("http://my-ollama:11434") == (
            "http://my-ollama:11434/v1"
        )


# ==============================================================================
# Import-boundary evidence — PAIM-C19
# ==============================================================================


def test_fresh_process_import_boundary() -> None:
    """Importing ``dnd_assistant.models.pydantic_ai_ollama`` in a fresh process
    must NOT eagerly load forbidden modules.

    Forbidden:
        dnd_assistant.application.pydantic_ai_agent_runtime
        dnd_assistant.storage
        dnd_assistant.retrieval
        dnd_assistant.cli
        dnd_assistant.tools.executor

    Allowed:
        pydantic_ai
        openai
        dnd_assistant.models.profiles
    """
    code = """import sys
sys.modules.pop('dnd_assistant.models.pydantic_ai_ollama', None)
import dnd_assistant.models.pydantic_ai_ollama
forbidden = [
    'dnd_assistant.application.pydantic_ai_agent_runtime',
    'dnd_assistant.storage',
    'dnd_assistant.retrieval',
    'dnd_assistant.cli',
    'dnd_assistant.tools.executor',
]
loaded = [m for m in sys.modules if any(m == f or m.startswith(f + '.') for f in forbidden)]
if loaded:
    print('FAIL: forbidden packages loaded:', loaded)
    sys.exit(1)
else:
    print('OK')
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, f"Fresh import failed: {result.stderr}"
    assert "OK" in result.stdout
