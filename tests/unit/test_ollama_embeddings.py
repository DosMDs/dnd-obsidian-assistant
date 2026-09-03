"""Tests for OllamaModelProvider.embed() (S8-05).

All tests use mocked HTTP (respx) — no real Ollama, no network, no Vault.

Covers:
    * Caller-input validation (before HTTP).
    * Request shape (endpoint, payload fields, path prefix).
    * Text preservation (order, duplicates, Unicode, whitespace, empty).
    * Successful single/batch embedding.
    * Integer-to-float conversion.
    * Duplicate-input handling.
    * Malformed top-level response.
    * Cardinality mismatch.
    * Malformed vectors.
    * Inconsistent dimensions.
    * Malformed scalars (None, string, bool, list, object).
    * Non-finite values (NaN, +Inf, -Inf).
    * Provider metadata ignored.
    * HTTP failure modes.
    * No-retry / exactly-one-request proof.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from dnd_assistant.errors import ModelError, ValidationError
from dnd_assistant.models.ollama import OllamaModelProvider
from dnd_assistant.models.profiles import ModelProfile, ModelProfileRole

# ── Helpers ────────────────────────────────────────────────────────────────


def _make_profile(
    *,
    provider: str = "ollama",
    model: str = "nomic-embed-text",
    base_url: str = "http://localhost:11434",
    temperature: float | None = None,
    keep_alive: str | None = None,
    role: ModelProfileRole = ModelProfileRole.EMBEDDING,
) -> ModelProfile:
    """Create a ModelProfile with sensible defaults for embedding tests."""
    return ModelProfile(
        provider=provider,
        model=model,
        base_url=base_url,
        temperature=temperature,
        keep_alive=keep_alive,
        role=role,
    )


def _embed_response(
    *vectors: list[float],
    extra_fields: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a valid Ollama ``/api/embed`` response body."""
    body: dict[str, Any] = {"embeddings": list(vectors)}
    if extra_fields:
        body.update(extra_fields)
    return body


def _assert_no_embed_called(respx_mock: respx.MockRouter) -> None:
    """Assert that ``/api/embed`` was never called."""
    for route in respx_mock.routes:
        if route.called:
            call_url = str(route.calls[0].request.url)
            if "/api/embed" in call_url:
                pytest.fail(f"/api/embed was called unexpectedly: {route.calls}")


# ═══════════════════════════════════════════════════════════════════════════
# Caller-input validation (before HTTP)
# ═══════════════════════════════════════════════════════════════════════════


class TestInputValidation:
    """Invalid caller inputs must raise ValidationError before any HTTP."""

    @pytest.mark.parametrize(
        "invalid_input",
        [
            pytest.param([], id="empty list"),
            pytest.param("hello", id="string"),
            pytest.param(("hello",), id="tuple"),
            pytest.param(123, id="integer"),
            pytest.param([123], id="list with int"),
            pytest.param([None], id="list with None"),
            pytest.param([["nested"]], id="list with list"),
        ],
    )
    def test_invalid_input_rejected_before_http(
        self, invalid_input: object, respx_mock: respx.MockRouter
    ) -> None:
        profile = _make_profile()
        provider = OllamaModelProvider(profile)

        with pytest.raises(ValidationError):
            provider.embed(invalid_input)  # type: ignore[arg-type]

        provider.close()
        _assert_no_embed_called(respx_mock)

    def test_empty_list_rejected(self, respx_mock: respx.MockRouter) -> None:
        profile = _make_profile()
        provider = OllamaModelProvider(profile)

        with pytest.raises(ValidationError):
            provider.embed([])

        provider.close()
        _assert_no_embed_called(respx_mock)


# ═══════════════════════════════════════════════════════════════════════════
# Text preservation
# ═══════════════════════════════════════════════════════════════════════════


class TestTextPreservation:
    """Input texts must be sent unchanged — no strip/dedup/normalization."""

    def test_order_preserved(self, respx_mock: respx.MockRouter) -> None:
        profile = _make_profile()
        provider = OllamaModelProvider(profile)
        texts = ["first", "second", "third"]

        embed_route = respx_mock.post("http://localhost:11434/api/embed").respond(
            json=_embed_response(
                [0.1, 0.2],
                [0.3, 0.4],
                [0.5, 0.6],
            )
        )

        result = provider.embed(texts)

        assert len(result) == 3
        assert embed_route.called
        sent = embed_route.calls[0].request.content
        body = json.loads(sent)
        assert body["input"] == ["first", "second", "third"]
        provider.close()

    def test_duplicates_preserved(self, respx_mock: respx.MockRouter) -> None:
        profile = _make_profile()
        provider = OllamaModelProvider(profile)
        texts = ["same", "same"]

        embed_route = respx_mock.post("http://localhost:11434/api/embed").respond(
            json=_embed_response([0.1, 0.2], [0.3, 0.4])
        )

        result = provider.embed(texts)

        assert len(result) == 2
        sent = json.loads(embed_route.calls[0].request.content)
        assert sent["input"] == ["same", "same"]
        provider.close()

    def test_unicode_preserved(self, respx_mock: respx.MockRouter) -> None:
        profile = _make_profile()
        provider = OllamaModelProvider(profile)
        texts = ["Брин", "你好", "αβγ"]

        embed_route = respx_mock.post("http://localhost:11434/api/embed").respond(
            json=_embed_response(
                [0.1],
                [0.2],
                [0.3],
            )
        )

        provider.embed(texts)

        sent = json.loads(embed_route.calls[0].request.content)
        assert sent["input"] == ["Брин", "你好", "αβγ"]
        provider.close()

    def test_whitespace_and_empty_preserved(self, respx_mock: respx.MockRouter) -> None:
        profile = _make_profile()
        provider = OllamaModelProvider(profile)
        texts = [" alpha ", "", "same", "same"]

        embed_route = respx_mock.post("http://localhost:11434/api/embed").respond(
            json=_embed_response(
                [0.1],
                [0.2],
                [0.3],
                [0.4],
            )
        )

        provider.embed(texts)

        sent = json.loads(embed_route.calls[0].request.content)
        assert sent["input"] == [" alpha ", "", "same", "same"]
        provider.close()


# ═══════════════════════════════════════════════════════════════════════════
# Request shape
# ═══════════════════════════════════════════════════════════════════════════


class TestRequestShape:
    """Verify exact endpoint, payload fields, and absent generation settings."""

    def test_exact_endpoint(self, respx_mock: respx.MockRouter) -> None:
        profile = _make_profile()
        provider = OllamaModelProvider(profile)

        embed_route = respx_mock.post("http://localhost:11434/api/embed").respond(
            json=_embed_response([0.1, 0.2])
        )

        provider.embed(["hello"])

        assert embed_route.called
        assert str(embed_route.calls[0].request.url) == ("http://localhost:11434/api/embed")
        provider.close()

    def test_payload_contains_model_input_truncate(self, respx_mock: respx.MockRouter) -> None:
        profile = _make_profile(model="nomic-embed-text:v1.5")
        provider = OllamaModelProvider(profile)

        embed_route = respx_mock.post("http://localhost:11434/api/embed").respond(
            json=_embed_response([0.1, 0.2])
        )

        provider.embed(["hello"])

        sent = json.loads(embed_route.calls[0].request.content)
        assert sent["model"] == "nomic-embed-text:v1.5"
        assert sent["input"] == ["hello"]
        assert sent["truncate"] is False
        provider.close()

    def test_single_input_still_array(self, respx_mock: respx.MockRouter) -> None:
        profile = _make_profile()
        provider = OllamaModelProvider(profile)

        embed_route = respx_mock.post("http://localhost:11434/api/embed").respond(
            json=_embed_response([0.1, 0.2])
        )

        provider.embed(["one"])

        sent = json.loads(embed_route.calls[0].request.content)
        assert sent["input"] == ["one"]
        assert isinstance(sent["input"], list)
        provider.close()

    def test_keep_alive_present_when_configured(self, respx_mock: respx.MockRouter) -> None:
        profile = _make_profile(keep_alive="5m")
        provider = OllamaModelProvider(profile)

        embed_route = respx_mock.post("http://localhost:11434/api/embed").respond(
            json=_embed_response([0.1, 0.2])
        )

        provider.embed(["hello"])

        sent = json.loads(embed_route.calls[0].request.content)
        assert sent["keep_alive"] == "5m"
        provider.close()

    def test_keep_alive_omitted_when_none(self, respx_mock: respx.MockRouter) -> None:
        profile = _make_profile(keep_alive=None)
        provider = OllamaModelProvider(profile)

        embed_route = respx_mock.post("http://localhost:11434/api/embed").respond(
            json=_embed_response([0.1, 0.2])
        )

        provider.embed(["hello"])

        sent = json.loads(embed_route.calls[0].request.content)
        assert "keep_alive" not in sent
        provider.close()

    def test_temperature_not_sent(self, respx_mock: respx.MockRouter) -> None:
        """Even with a non-None temperature, it must not appear in the payload."""
        profile = _make_profile(temperature=0.7)
        provider = OllamaModelProvider(profile)

        embed_route = respx_mock.post("http://localhost:11434/api/embed").respond(
            json=_embed_response([0.1, 0.2])
        )

        provider.embed(["hello"])

        sent = json.loads(embed_route.calls[0].request.content)
        assert "temperature" not in sent
        assert "options" not in sent
        provider.close()

    def test_no_generation_settings_sent(self, respx_mock: respx.MockRouter) -> None:
        """Verify absence of stream, format, tools, think, dimensions, options."""
        profile = _make_profile()
        provider = OllamaModelProvider(profile)

        embed_route = respx_mock.post("http://localhost:11434/api/embed").respond(
            json=_embed_response([0.1, 0.2])
        )

        provider.embed(["hello"])

        sent = json.loads(embed_route.calls[0].request.content)
        assert "stream" not in sent
        assert "format" not in sent
        assert "tools" not in sent
        assert "think" not in sent
        assert "dimensions" not in sent
        assert "options" not in sent
        provider.close()


# ═══════════════════════════════════════════════════════════════════════════
# Path-prefix preservation
# ═══════════════════════════════════════════════════════════════════════════


class TestPathPrefix:
    """With a path-prefixed base_url, the endpoint must preserve the prefix."""

    def test_path_prefix_preserved(self, respx_mock: respx.MockRouter) -> None:
        profile = _make_profile(base_url="https://provider.example/ollama")
        provider = OllamaModelProvider(profile)

        embed_route = respx_mock.post("https://provider.example/ollama/api/embed").respond(
            json=_embed_response([0.1, 0.2])
        )

        provider.embed(["hello"])

        assert embed_route.called
        assert str(embed_route.calls[0].request.url) == (
            "https://provider.example/ollama/api/embed"
        )
        provider.close()


# ═══════════════════════════════════════════════════════════════════════════
# Successful embedding
# ═══════════════════════════════════════════════════════════════════════════


class TestSuccessfulEmbedding:
    """Normal embedding responses are parsed correctly."""

    def test_single_input(self, respx_mock: respx.MockRouter) -> None:
        profile = _make_profile()
        provider = OllamaModelProvider(profile)

        respx_mock.post("http://localhost:11434/api/embed").respond(
            json=_embed_response([0.1, 0.2, 0.3])
        )

        result = provider.embed(["hello"])

        assert result == [[0.1, 0.2, 0.3]]
        # Verify every scalar is a Python float
        for val in result[0]:
            assert isinstance(val, float)
        provider.close()

    def test_batch_order_preserved(self, respx_mock: respx.MockRouter) -> None:
        profile = _make_profile()
        provider = OllamaModelProvider(profile)

        respx_mock.post("http://localhost:11434/api/embed").respond(
            json=_embed_response(
                [0.1, 0.1],
                [0.2, 0.2],
                [0.3, 0.3],
            )
        )

        result = provider.embed(["a", "b", "c"])

        assert len(result) == 3
        assert result[0] == [0.1, 0.1]
        assert result[1] == [0.2, 0.2]
        assert result[2] == [0.3, 0.3]
        provider.close()

    def test_integer_values_converted_to_float(self, respx_mock: respx.MockRouter) -> None:
        profile = _make_profile()
        provider = OllamaModelProvider(profile)

        # Mock raw JSON with integer values
        respx_mock.post("http://localhost:11434/api/embed").respond(
            json=_embed_response([1, 2.5, -3])
        )

        result = provider.embed(["hello"])

        assert result == [[1.0, 2.5, -3.0]]
        for val in result[0]:
            assert isinstance(val, float)
        provider.close()

    def test_duplicate_inputs_return_two_vectors(self, respx_mock: respx.MockRouter) -> None:
        profile = _make_profile()
        provider = OllamaModelProvider(profile)

        respx_mock.post("http://localhost:11434/api/embed").respond(
            json=_embed_response([0.1, 0.2], [0.3, 0.4])
        )

        result = provider.embed(["same", "same"])

        assert len(result) == 2
        assert result[0] == [0.1, 0.2]
        assert result[1] == [0.3, 0.4]
        provider.close()

    def test_provider_metadata_ignored(self, respx_mock: respx.MockRouter) -> None:
        profile = _make_profile()
        provider = OllamaModelProvider(profile)

        respx_mock.post("http://localhost:11434/api/embed").respond(
            json=_embed_response(
                [0.1, 0.2],
                extra_fields={
                    "model": "nomic-embed-text",
                    "total_duration": 123456,
                    "load_duration": 50000,
                    "prompt_eval_count": 7,
                },
            )
        )

        result = provider.embed(["hello"])

        assert result == [[0.1, 0.2]]
        provider.close()


# ═══════════════════════════════════════════════════════════════════════════
# Malformed top-level response
# ═══════════════════════════════════════════════════════════════════════════


class TestMalformedTopLevelResponse:
    """Malformed top-level response structure must raise ModelError."""

    @pytest.mark.parametrize(
        "malformed_body",
        [
            pytest.param([], id="top-level list"),
            pytest.param("invalid", id="top-level string"),
            pytest.param({"no_embeddings": True}, id="missing embeddings"),
            pytest.param({"embeddings": None}, id="embeddings is None"),
            pytest.param({"embeddings": {}}, id="embeddings is object"),
            pytest.param({"embeddings": "string"}, id="embeddings is string"),
        ],
    )
    def test_malformed_top_level(
        self, malformed_body: object, respx_mock: respx.MockRouter
    ) -> None:
        profile = _make_profile()
        provider = OllamaModelProvider(profile)

        respx_mock.post("http://localhost:11434/api/embed").respond(
            json=malformed_body  # type: ignore[arg-type]
        )

        with pytest.raises(ModelError):
            provider.embed(["hello"])

        provider.close()


# ═══════════════════════════════════════════════════════════════════════════
# Cardinality mismatch
# ═══════════════════════════════════════════════════════════════════════════


class TestCardinalityMismatch:
    """Returned vector count must match input count."""

    @pytest.mark.parametrize(
        ("input_texts", "response_vectors"),
        [
            pytest.param(["a", "b"], [[0.1]], id="2 inputs 1 vector"),
            pytest.param(["a"], [[0.1], [0.2]], id="1 input 2 vectors"),
            pytest.param(["a"], [], id="1 input 0 vectors"),
        ],
    )
    def test_cardinality_mismatch(
        self,
        input_texts: list[str],
        response_vectors: list[list[float]],
        respx_mock: respx.MockRouter,
    ) -> None:
        profile = _make_profile()
        provider = OllamaModelProvider(profile)

        respx_mock.post("http://localhost:11434/api/embed").respond(
            json=_embed_response(*response_vectors)
        )

        with pytest.raises(ModelError):
            provider.embed(input_texts)

        provider.close()


# ═══════════════════════════════════════════════════════════════════════════
# Malformed vectors
# ═══════════════════════════════════════════════════════════════════════════


class TestMalformedVectors:
    """Each embedding vector must be a non-empty list."""

    @pytest.mark.parametrize(
        "bad_vector",
        [
            pytest.param(None, id="vector is None"),
            pytest.param("string", id="vector is string"),
            pytest.param({}, id="vector is object"),
            pytest.param(123, id="vector is number"),
            pytest.param([], id="vector is empty"),
        ],
    )
    def test_malformed_vector(self, bad_vector: object, respx_mock: respx.MockRouter) -> None:
        profile = _make_profile()
        provider = OllamaModelProvider(profile)

        respx_mock.post("http://localhost:11434/api/embed").respond(
            json={"embeddings": [bad_vector]}
        )

        with pytest.raises(ModelError):
            provider.embed(["hello"])

        provider.close()


# ═══════════════════════════════════════════════════════════════════════════
# Inconsistent dimensions
# ═══════════════════════════════════════════════════════════════════════════


class TestInconsistentDimensions:
    """All returned vectors must have the same non-zero length."""

    def test_ragged_dimensions_rejected(self, respx_mock: respx.MockRouter) -> None:
        profile = _make_profile()
        provider = OllamaModelProvider(profile)

        respx_mock.post("http://localhost:11434/api/embed").respond(
            json=_embed_response([0.1, 0.2], [0.3, 0.4, 0.5])
        )

        with pytest.raises(ModelError):
            provider.embed(["a", "b"])

        provider.close()


# ═══════════════════════════════════════════════════════════════════════════
# Malformed scalars
# ═══════════════════════════════════════════════════════════════════════════


class TestMalformedScalars:
    """Each scalar in a vector must be a numeric value."""

    @pytest.mark.parametrize(
        "bad_scalar",
        [
            pytest.param(None, id="scalar is None"),
            pytest.param("0.5", id="scalar is string"),
            pytest.param(True, id="scalar is bool (True)"),
            pytest.param(False, id="scalar is bool (False)"),
            pytest.param([], id="scalar is list"),
            pytest.param({}, id="scalar is object"),
        ],
    )
    def test_malformed_scalar(self, bad_scalar: object, respx_mock: respx.MockRouter) -> None:
        profile = _make_profile()
        provider = OllamaModelProvider(profile)

        respx_mock.post("http://localhost:11434/api/embed").respond(
            json={"embeddings": [[bad_scalar]]}
        )

        with pytest.raises(ModelError):
            provider.embed(["hello"])

        provider.close()


# ═══════════════════════════════════════════════════════════════════════════
# Non-finite values
# ═══════════════════════════════════════════════════════════════════════════


class TestNonFiniteValues:
    """NaN, Infinity, and -Infinity must be rejected."""

    @pytest.mark.parametrize(
        ("raw_bytes", "description"),
        [
            pytest.param(
                b'{"embeddings": [[NaN]]}',
                "NaN",
            ),
            pytest.param(
                b'{"embeddings": [[Infinity]]}',
                "+Infinity",
            ),
            pytest.param(
                b'{"embeddings": [[-Infinity]]}',
                "-Infinity",
            ),
        ],
    )
    def test_non_finite_rejected(
        self,
        raw_bytes: bytes,
        description: str,
        respx_mock: respx.MockRouter,
    ) -> None:
        profile = _make_profile()
        provider = OllamaModelProvider(profile)

        respx_mock.post("http://localhost:11434/api/embed").respond(
            content=raw_bytes,
            headers={"content-type": "application/json"},
        )

        with pytest.raises(ModelError):
            provider.embed(["hello"])

        provider.close()


# ═══════════════════════════════════════════════════════════════════════════
# HTTP failure modes
# ═══════════════════════════════════════════════════════════════════════════


class TestHttpFailures:
    """Network and HTTP errors must map to ModelError."""

    def test_connection_failure(self, respx_mock: respx.MockRouter) -> None:
        profile = _make_profile()
        provider = OllamaModelProvider(profile)

        respx_mock.post("http://localhost:11434/api/embed").mock(
            side_effect=httpx.ConnectError("connection refused")
        )

        with pytest.raises(ModelError) as exc_info:
            provider.embed(["hello"])

        assert isinstance(exc_info.value.__cause__, httpx.ConnectError)
        provider.close()

    def test_timeout(self, respx_mock: respx.MockRouter) -> None:
        profile = _make_profile()
        provider = OllamaModelProvider(profile)

        respx_mock.post("http://localhost:11434/api/embed").mock(
            side_effect=httpx.TimeoutException("timed out")
        )

        with pytest.raises(ModelError) as exc_info:
            provider.embed(["hello"])

        assert isinstance(exc_info.value.__cause__, httpx.TimeoutException)
        provider.close()

    @pytest.mark.parametrize(
        ("status_code", "response_body"),
        [
            pytest.param(400, {"error": "bad request"}, id="HTTP 400"),
            pytest.param(404, {"error": "not found"}, id="HTTP 404"),
            pytest.param(500, {"error": "internal error"}, id="HTTP 500"),
        ],
    )
    def test_http_error_with_json_body(
        self,
        status_code: int,
        response_body: dict[str, object],
        respx_mock: respx.MockRouter,
    ) -> None:
        profile = _make_profile()
        provider = OllamaModelProvider(profile)

        respx_mock.post("http://localhost:11434/api/embed").respond(
            status_code=status_code,
            json=response_body,
        )

        with pytest.raises(ModelError) as exc_info:
            provider.embed(["hello"])

        error_msg = str(exc_info.value)
        assert str(status_code) in error_msg
        provider.close()

    def test_http_error_non_json_body(self, respx_mock: respx.MockRouter) -> None:
        profile = _make_profile()
        provider = OllamaModelProvider(profile)

        respx_mock.post("http://localhost:11434/api/embed").respond(
            status_code=500,
            content=b"Internal Server Error",
        )

        with pytest.raises(ModelError) as exc_info:
            provider.embed(["hello"])

        error_msg = str(exc_info.value)
        assert "500" in error_msg
        provider.close()

    def test_http_error_invalid_byte_body(self, respx_mock: respx.MockRouter) -> None:
        profile = _make_profile()
        provider = OllamaModelProvider(profile)

        respx_mock.post("http://localhost:11434/api/embed").respond(
            status_code=400,
            content=b"\xff\xfe\x00\x01",
        )

        with pytest.raises(ModelError) as exc_info:
            provider.embed(["hello"])

        error_msg = str(exc_info.value)
        assert "400" in error_msg
        provider.close()

    def test_success_http_non_json_body(self, respx_mock: respx.MockRouter) -> None:
        profile = _make_profile()
        provider = OllamaModelProvider(profile)

        respx_mock.post("http://localhost:11434/api/embed").respond(
            content=b"not json at all",
        )

        with pytest.raises(ModelError) as exc_info:
            provider.embed(["hello"])

        assert isinstance(exc_info.value.__cause__, ValueError)
        provider.close()

    def test_success_http_invalid_byte_body(self, respx_mock: respx.MockRouter) -> None:
        profile = _make_profile()
        provider = OllamaModelProvider(profile)

        respx_mock.post("http://localhost:11434/api/embed").respond(
            content=b"\xff\xfe\x00\x01",
        )

        with pytest.raises(ModelError) as exc_info:
            provider.embed(["hello"])

        assert isinstance(exc_info.value.__cause__, ValueError)
        provider.close()


# ═══════════════════════════════════════════════════════════════════════════
# Exactly-one-request / no-retry proof
# ═══════════════════════════════════════════════════════════════════════════


class TestExactlyOneRequest:
    """A single Gateway invocation must perform exactly one HTTP request."""

    def test_success_makes_one_request(self, respx_mock: respx.MockRouter) -> None:
        profile = _make_profile()
        provider = OllamaModelProvider(profile)

        embed_route = respx_mock.post("http://localhost:11434/api/embed").respond(
            json=_embed_response([0.1, 0.2])
        )

        provider.embed(["hello"])

        assert len(embed_route.calls) == 1
        provider.close()

    def test_provider_error_no_retry(self, respx_mock: respx.MockRouter) -> None:
        profile = _make_profile()
        provider = OllamaModelProvider(profile)

        embed_route = respx_mock.post("http://localhost:11434/api/embed").respond(
            status_code=400,
            json={"error": "input too long"},
        )

        with pytest.raises(ModelError):
            provider.embed(["hello"])

        assert len(embed_route.calls) == 1
        provider.close()


# ═══════════════════════════════════════════════════════════════════════════
# No silent truncation
# ═══════════════════════════════════════════════════════════════════════════


class TestNoSilentTruncation:
    """truncate must be explicitly False and no retry occurs on context error."""

    def test_truncate_is_false(self, respx_mock: respx.MockRouter) -> None:
        profile = _make_profile()
        provider = OllamaModelProvider(profile)

        embed_route = respx_mock.post("http://localhost:11434/api/embed").respond(
            json=_embed_response([0.1, 0.2])
        )

        provider.embed(["hello"])

        sent = json.loads(embed_route.calls[0].request.content)
        assert sent["truncate"] is False
        assert len(embed_route.calls) == 1
        provider.close()

    def test_context_error_no_retry_with_truncation(self, respx_mock: respx.MockRouter) -> None:
        """A context-length error must not trigger a retry with truncation."""
        profile = _make_profile()
        provider = OllamaModelProvider(profile)

        embed_route = respx_mock.post("http://localhost:11434/api/embed").respond(
            status_code=400,
            json={"error": "input length exceeds context length"},
        )

        with pytest.raises(ModelError):
            provider.embed(["hello"])

        assert len(embed_route.calls) == 1
        provider.close()


# ═══════════════════════════════════════════════════════════════════════════
# Oversized integer regression (S8-C06)
# ═══════════════════════════════════════════════════════════════════════════


class TestOversizedIntegers:
    """JSON integers too large for float must produce ModelError, not OverflowError."""

    def test_oversized_positive_int_public_boundary(self, respx_mock: respx.MockRouter) -> None:
        """A positive int too large for float must raise ModelError with OverflowError cause."""
        huge = 10**309
        profile = _make_profile()
        provider = OllamaModelProvider(profile)

        respx_mock.post("http://localhost:11434/api/embed").respond(json={"embeddings": [[huge]]})

        with pytest.raises(ModelError) as exc_info:
            provider.embed(["hello"])

        assert isinstance(exc_info.value.__cause__, OverflowError)
        provider.close()

    def test_oversized_negative_int_public_boundary(self, respx_mock: respx.MockRouter) -> None:
        """A negative int too large for float must raise ModelError with OverflowError cause."""
        huge = -(10**309)
        profile = _make_profile()
        provider = OllamaModelProvider(profile)

        respx_mock.post("http://localhost:11434/api/embed").respond(json={"embeddings": [[huge]]})

        with pytest.raises(ModelError) as exc_info:
            provider.embed(["hello"])

        assert isinstance(exc_info.value.__cause__, OverflowError)
        provider.close()

    def test_ordinary_positive_int_still_accepted(self, respx_mock: respx.MockRouter) -> None:
        """Ordinary positive ints must still be accepted and converted to float."""
        profile = _make_profile()
        provider = OllamaModelProvider(profile)

        respx_mock.post("http://localhost:11434/api/embed").respond(json=_embed_response([42]))

        result = provider.embed(["hello"])

        assert result == [[42.0]]
        assert isinstance(result[0][0], float)
        provider.close()

    def test_ordinary_negative_int_still_accepted(self, respx_mock: respx.MockRouter) -> None:
        """Ordinary negative ints must still be accepted and converted to float."""
        profile = _make_profile()
        provider = OllamaModelProvider(profile)

        respx_mock.post("http://localhost:11434/api/embed").respond(json=_embed_response([-7]))

        result = provider.embed(["hello"])

        assert result == [[-7.0]]
        assert isinstance(result[0][0], float)
        provider.close()

    def test_oversized_int_in_batch(self, respx_mock: respx.MockRouter) -> None:
        """An oversized int in a batch must raise ModelError, not OverflowError."""
        huge = 10**309
        profile = _make_profile()
        provider = OllamaModelProvider(profile)

        respx_mock.post("http://localhost:11434/api/embed").respond(
            json={"embeddings": [[0.1, 0.2], [huge, 0.5]]}
        )

        with pytest.raises(ModelError) as exc_info:
            provider.embed(["a", "b"])

        assert isinstance(exc_info.value.__cause__, OverflowError)
        provider.close()
