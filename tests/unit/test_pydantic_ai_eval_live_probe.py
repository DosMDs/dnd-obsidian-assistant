"""PAIM-C33: Offline tests for the PAIM-13 live environment probe.

Tests ``probe_ollama_environment()`` and ``Paim13OllamaEnvironment``
with mocked HTTP (respx) — no real network, no Ollama, no model.

Positive tests:
    valid health + version
    different version string

Negative tests:
    unreachable server
    configured model unavailable
    /api/version HTTP error
    /api/version non-JSON
    /api/version missing "version" field
    /api/version empty version string
    /api/version whitespace-only version

Architecture tests:
    no ``OllamaModelProvider.version()`` call in probe or live fixtures
"""

from __future__ import annotations

import pytest
import respx


class TestPaim13LiveProbePositive:
    """Positive offline tests for ``probe_ollama_environment``.

    Uses ``respx`` to mock Ollama HTTP endpoints — no real network.
    """

    def test_probe_succeeds_with_valid_health_and_version(
        self, respx_mock: respx.MockRouter
    ) -> None:
        """probe_ollama_environment: PASS with reachable server and available model."""
        from dnd_assistant.models.profiles import ModelProfile, ModelProfileRole
        from tests.support.paim13_live_harness import probe_ollama_environment

        profile = ModelProfile(
            provider="ollama",
            model="qwen-2.5-7b",
            base_url="http://localhost:11434",
            role=ModelProfileRole.AGENT,
            keep_alive=None,
        )

        # Mock /api/version (called by both health() and _fetch_ollama_server_version)
        respx_mock.get("http://localhost:11434/api/version").respond(
            200, json={"version": "0.33.3"}
        )
        # Mock /api/tags (called by health())
        respx_mock.get("http://localhost:11434/api/tags").respond(
            200,
            json={
                "models": [
                    {"name": "qwen-2.5-7b", "modified_at": "2024-01-01T00:00:00Z", "size": 1000}
                ]
            },
        )

        env = probe_ollama_environment(profile)

        assert env.reachable is True
        assert env.model_available is True
        assert env.model_name == "qwen-2.5-7b"
        assert env.server_version == "0.33.3"

    def test_probe_succeeds_with_different_version(self, respx_mock: respx.MockRouter) -> None:
        """probe_ollama_environment: PASS with a different version string."""
        from dnd_assistant.models.profiles import ModelProfile, ModelProfileRole
        from tests.support.paim13_live_harness import probe_ollama_environment

        profile = ModelProfile(
            provider="ollama",
            model="llama-3.2-3b",
            base_url="http://localhost:11434",
            role=ModelProfileRole.AGENT,
            keep_alive=None,
        )

        respx_mock.get("http://localhost:11434/api/version").respond(
            200, json={"version": "0.40.0"}
        )
        respx_mock.get("http://localhost:11434/api/tags").respond(
            200,
            json={
                "models": [
                    {"name": "llama-3.2-3b", "modified_at": "2024-06-01T00:00:00Z", "size": 2000}
                ]
            },
        )

        env = probe_ollama_environment(profile)

        assert env.server_version == "0.40.0"
        assert env.model_name == "llama-3.2-3b"


class TestPaim13LiveProbeNegative:
    """Negative offline tests for ``probe_ollama_environment``.

    All cases must raise ``AssertionError`` (fail, not skip).
    """

    def test_probe_fails_when_unreachable(self, respx_mock: respx.MockRouter) -> None:
        """probe_ollama_environment: FAIL when server is unreachable."""
        import httpx

        from dnd_assistant.models.profiles import ModelProfile, ModelProfileRole
        from tests.support.paim13_live_harness import probe_ollama_environment

        profile = ModelProfile(
            provider="ollama",
            model="qwen-2.5-7b",
            base_url="http://localhost:11434",
            role=ModelProfileRole.AGENT,
            keep_alive=None,
        )

        # Simulate connection error by raising RequestError from the mock
        respx_mock.get("http://localhost:11434/api/version").mock(
            side_effect=httpx.RequestError("Connection refused")
        )

        with pytest.raises(AssertionError, match="not reachable"):
            probe_ollama_environment(profile)

    def test_probe_fails_when_model_unavailable(self, respx_mock: respx.MockRouter) -> None:
        """probe_ollama_environment: FAIL when configured model not in /api/tags."""
        from dnd_assistant.models.profiles import ModelProfile, ModelProfileRole
        from tests.support.paim13_live_harness import probe_ollama_environment

        profile = ModelProfile(
            provider="ollama",
            model="nonexistent-model",
            base_url="http://localhost:11434",
            role=ModelProfileRole.AGENT,
            keep_alive=None,
        )

        respx_mock.get("http://localhost:11434/api/version").respond(
            200, json={"version": "0.33.3"}
        )
        respx_mock.get("http://localhost:11434/api/tags").respond(
            200,
            json={
                "models": [
                    {"name": "qwen-2.5-7b", "modified_at": "2024-01-01T00:00:00Z", "size": 1000}
                ]
            },
        )

        with pytest.raises(AssertionError, match="not available"):
            probe_ollama_environment(profile)

    def test_probe_fails_when_version_http_error(self, respx_mock: respx.MockRouter) -> None:
        """probe_ollama_environment: FAIL when /api/version returns HTTP error."""
        from dnd_assistant.models.profiles import ModelProfile, ModelProfileRole
        from tests.support.paim13_live_harness import probe_ollama_environment

        profile = ModelProfile(
            provider="ollama",
            model="qwen-2.5-7b",
            base_url="http://localhost:11434",
            role=ModelProfileRole.AGENT,
            keep_alive=None,
        )

        # health() succeeds (it checks reachability via /api/version HTTP status)
        # but _fetch_ollama_server_version gets the same response — HTTP 500
        respx_mock.get("http://localhost:11434/api/version").respond(500)
        respx_mock.get("http://localhost:11434/api/tags").respond(
            200,
            json={
                "models": [
                    {"name": "qwen-2.5-7b", "modified_at": "2024-01-01T00:00:00Z", "size": 1000}
                ]
            },
        )

        with pytest.raises(AssertionError, match="HTTP 500"):
            probe_ollama_environment(profile)

    def test_probe_fails_when_version_non_json(self, respx_mock: respx.MockRouter) -> None:
        """probe_ollama_environment: FAIL when /api/version returns non-JSON."""
        from dnd_assistant.models.profiles import ModelProfile, ModelProfileRole
        from tests.support.paim13_live_harness import probe_ollama_environment

        profile = ModelProfile(
            provider="ollama",
            model="qwen-2.5-7b",
            base_url="http://localhost:11434",
            role=ModelProfileRole.AGENT,
            keep_alive=None,
        )

        # health() succeeds (it checks reachability via HTTP status, then JSON)
        # _fetch_ollama_server_version gets the same body
        respx_mock.get("http://localhost:11434/api/version").respond(
            200, content=b"not json at all"
        )
        respx_mock.get("http://localhost:11434/api/tags").respond(
            200,
            json={
                "models": [
                    {"name": "qwen-2.5-7b", "modified_at": "2024-01-01T00:00:00Z", "size": 1000}
                ]
            },
        )

        with pytest.raises(AssertionError, match="non-JSON"):
            probe_ollama_environment(profile)

    def test_probe_fails_when_version_missing_field(self, respx_mock: respx.MockRouter) -> None:
        """probe_ollama_environment: FAIL when /api/version JSON lacks 'version'."""
        from dnd_assistant.models.profiles import ModelProfile, ModelProfileRole
        from tests.support.paim13_live_harness import probe_ollama_environment

        profile = ModelProfile(
            provider="ollama",
            model="qwen-2.5-7b",
            base_url="http://localhost:11434",
            role=ModelProfileRole.AGENT,
            keep_alive=None,
        )

        respx_mock.get("http://localhost:11434/api/version").respond(200, json={"foo": "bar"})
        respx_mock.get("http://localhost:11434/api/tags").respond(
            200,
            json={
                "models": [
                    {"name": "qwen-2.5-7b", "modified_at": "2024-01-01T00:00:00Z", "size": 1000}
                ]
            },
        )

        with pytest.raises(AssertionError, match="not available"):
            probe_ollama_environment(profile)

    def test_probe_fails_when_version_empty_string(self, respx_mock: respx.MockRouter) -> None:
        """probe_ollama_environment: FAIL when version is empty string."""
        from dnd_assistant.models.profiles import ModelProfile, ModelProfileRole
        from tests.support.paim13_live_harness import probe_ollama_environment

        profile = ModelProfile(
            provider="ollama",
            model="qwen-2.5-7b",
            base_url="http://localhost:11434",
            role=ModelProfileRole.AGENT,
            keep_alive=None,
        )

        respx_mock.get("http://localhost:11434/api/version").respond(200, json={"version": ""})
        respx_mock.get("http://localhost:11434/api/tags").respond(
            200,
            json={
                "models": [
                    {"name": "qwen-2.5-7b", "modified_at": "2024-01-01T00:00:00Z", "size": 1000}
                ]
            },
        )

        with pytest.raises(AssertionError, match="not available"):
            probe_ollama_environment(profile)

    def test_probe_fails_when_version_whitespace(self, respx_mock: respx.MockRouter) -> None:
        """probe_ollama_environment: FAIL when version is whitespace-only."""
        from dnd_assistant.models.profiles import ModelProfile, ModelProfileRole
        from tests.support.paim13_live_harness import probe_ollama_environment

        profile = ModelProfile(
            provider="ollama",
            model="qwen-2.5-7b",
            base_url="http://localhost:11434",
            role=ModelProfileRole.AGENT,
            keep_alive=None,
        )

        respx_mock.get("http://localhost:11434/api/version").respond(200, json={"version": "   "})
        respx_mock.get("http://localhost:11434/api/tags").respond(
            200,
            json={
                "models": [
                    {"name": "qwen-2.5-7b", "modified_at": "2024-01-01T00:00:00Z", "size": 1000}
                ]
            },
        )

        with pytest.raises(AssertionError, match="not available"):
            probe_ollama_environment(profile)


class TestPaim13LiveProbeArchitecture:
    """Architecture assertions for the PAIM-13 live probe.

    Verifies that the live fixture does not depend on a nonexistent
    ``OllamaModelProvider.version()`` method.
    """

    def test_no_ollama_model_provider_version_used(self) -> None:
        """The PAIM-13 live probe does not call ``OllamaModelProvider.version()``.

        Verifies that the shared probe function and both live modules
        do not reference a nonexistent ``version`` attribute on
        ``OllamaModelProvider``.
        """
        import ast
        from pathlib import Path

        # Check the shared probe module
        probe_path = (
            Path(__file__).resolve().parent.parent.parent
            / "tests"
            / "support"
            / "paim13_live_harness.py"
        )
        probe_source = probe_path.read_text(encoding="utf-8")
        assert "native.version()" not in probe_source, "Shared probe must not call native.version()"

        # Check both live integration modules
        for module_name in [
            "test_pydantic_ai_stage9_live_eval_decision.py",
            "test_pydantic_ai_stage9_live_eval_full_turn.py",
        ]:
            module_path = (
                Path(__file__).resolve().parent.parent.parent
                / "tests"
                / "integration"
                / module_name
            )
            source = module_path.read_text(encoding="utf-8")
            assert "native.version()" not in source, f"{module_name} must not call native.version()"

            # Parse AST to verify paim13_config function body
            # does not use OllamaModelProvider directly
            tree = ast.parse(source)
            paim13_config_found = False
            for node in ast.walk(tree):
                if isinstance(node, ast.FunctionDef) and node.name == "paim13_config":
                    paim13_config_found = True
                    func_source = ast.get_source_segment(source, node)
                    assert func_source is not None
                    assert "OllamaModelProvider" not in func_source, (
                        f"{module_name} paim13_config must not use OllamaModelProvider directly"
                    )
                    break
            assert paim13_config_found, f"{module_name} must define a paim13_config fixture"
