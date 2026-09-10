"""Tests for the project-owned Ollama HTTP transport timeout policy (PAIM-C38).

All tests are deterministic and require no real Ollama or network access.
"""

from __future__ import annotations

import httpx

from dnd_assistant.models.transport import (
    OLLAMA_CONNECT_TIMEOUT_SECONDS,
    OLLAMA_REQUEST_TIMEOUT_SECONDS,
    build_ollama_http_timeout,
)


class TestTimeoutConstants:
    """Verify the project-owned timeout constant values."""

    def test_connect_timeout_is_5(self) -> None:
        assert OLLAMA_CONNECT_TIMEOUT_SECONDS == 5.0

    def test_request_timeout_is_120(self) -> None:
        assert OLLAMA_REQUEST_TIMEOUT_SECONDS == 120.0


class TestBuildOllamaHttpTimeout:
    """Verify the timeout factory function."""

    def test_returns_httpx_timeout(self) -> None:
        result = build_ollama_http_timeout()
        assert isinstance(result, httpx.Timeout)

    def test_connect_timeout_matches_constant(self) -> None:
        result = build_ollama_http_timeout()
        assert result.connect == OLLAMA_CONNECT_TIMEOUT_SECONDS

    def test_read_timeout_matches_constant(self) -> None:
        result = build_ollama_http_timeout()
        assert result.read == OLLAMA_REQUEST_TIMEOUT_SECONDS

    def test_write_timeout_is_bounded(self) -> None:
        """Write timeout should be bounded (not None)."""
        result = build_ollama_http_timeout()
        assert result.write is not None

    def test_pool_timeout_is_bounded(self) -> None:
        """Pool timeout should be bounded (not None)."""
        result = build_ollama_http_timeout()
        assert result.pool is not None

    def test_fresh_call_returns_independent_object(self) -> None:
        """Each call to the factory must return a new timeout object."""
        t1 = build_ollama_http_timeout()
        t2 = build_ollama_http_timeout()
        assert t1 is not t2
        # Both must have the same effective values
        assert t1.connect == t2.connect
        assert t1.read == t2.read


class TestTimeoutOriginParity:
    """Prove that both native and candidate transports use the SAME policy.

    These tests verify that the timeout factory/constants are shared by
    reference, not duplicated as separate literals.
    """

    def test_native_provider_imports_shared_factory(self) -> None:
        """The native Ollama provider imports ``build_ollama_http_timeout``."""
        # We verify the import path exists in the production module
        import inspect

        from dnd_assistant.models import ollama

        source = inspect.getsource(ollama)
        assert "from dnd_assistant.models.transport import build_ollama_http_timeout" in source

    def test_candidate_builder_imports_shared_factory(self) -> None:
        """The Pydantic AI builder imports ``build_ollama_http_timeout``."""
        import inspect

        from dnd_assistant.models import pydantic_ai_ollama

        source = inspect.getsource(pydantic_ai_ollama)
        assert "from dnd_assistant.models.transport import build_ollama_http_timeout" in source


class TestNativeProviderTimeout:
    """Prove that ``OllamaModelProvider`` uses the explicit project timeout."""

    def test_client_created_with_project_timeout(self) -> None:
        """The HTTPX client created by ``OllamaModelProvider`` must use
        the project-owned timeout values.
        """
        from dnd_assistant.models.ollama import OllamaModelProvider
        from dnd_assistant.models.profiles import ModelProfile, ModelProfileRole

        profile = ModelProfile(
            provider="ollama",
            model="test-model",
            base_url="http://localhost:11434",
            role=ModelProfileRole.AGENT,
        )
        provider = OllamaModelProvider(profile)
        try:
            client = provider._client
            assert isinstance(client, httpx.Client)
            timeout = client.timeout
            assert timeout.connect == OLLAMA_CONNECT_TIMEOUT_SECONDS
            assert timeout.read == OLLAMA_REQUEST_TIMEOUT_SECONDS
        finally:
            provider.close()


class TestPydanticAiBuilderTimeout:
    """Prove that ``build_pydantic_ai_ollama_model`` propagates the project
    timeout through ``ModelSettings.timeout``.
    """

    def test_timeout_present_when_temperature_none(self) -> None:
        """``temperature=None`` must still include the project timeout."""
        from dnd_assistant.models.profiles import ModelProfile, ModelProfileRole
        from dnd_assistant.models.pydantic_ai_ollama import (
            build_pydantic_ai_ollama_model,
        )

        profile = ModelProfile(
            provider="ollama",
            model="test-model",
            base_url="http://localhost:11434",
            role=ModelProfileRole.AGENT,
            temperature=None,
        )
        model = build_pydantic_ai_ollama_model(profile)
        assert model.settings is not None
        timeout = model.settings.get("timeout")
        assert timeout is not None
        assert isinstance(timeout, httpx.Timeout)
        assert timeout.connect == OLLAMA_CONNECT_TIMEOUT_SECONDS
        assert timeout.read == OLLAMA_REQUEST_TIMEOUT_SECONDS
        # temperature must NOT be present
        assert "temperature" not in model.settings

    def test_timeout_present_with_temperature(self) -> None:
        """``temperature=0.25`` must retain both the exact temperature and
        the project timeout.
        """
        from dnd_assistant.models.profiles import ModelProfile, ModelProfileRole
        from dnd_assistant.models.pydantic_ai_ollama import (
            build_pydantic_ai_ollama_model,
        )

        profile = ModelProfile(
            provider="ollama",
            model="test-model",
            base_url="http://localhost:11434",
            role=ModelProfileRole.AGENT,
            temperature=0.25,
        )
        model = build_pydantic_ai_ollama_model(profile)
        assert model.settings is not None
        # Temperature must be preserved
        assert model.settings.get("temperature") == 0.25
        # Timeout must also be present
        timeout = model.settings.get("timeout")
        assert timeout is not None
        assert isinstance(timeout, httpx.Timeout)
        assert timeout.connect == OLLAMA_CONNECT_TIMEOUT_SECONDS
        assert timeout.read == OLLAMA_REQUEST_TIMEOUT_SECONDS
