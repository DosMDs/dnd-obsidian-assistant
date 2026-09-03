"""Ollama-specific embedding request/response adaptation.

This module provides provider-specific pure-ish validation and adaptation
for the ``POST /api/embed`` endpoint.  It is imported by
``OllamaModelProvider.embed()`` and is not part of the public
``dnd_assistant.models`` package API.

Responsibilities
────────────────
* Validate caller-provided embedding inputs (``validate_embed_inputs``).
* Build the Ollama ``/api/embed`` JSON payload (``build_embed_payload``).
* Parse and validate the Ollama ``/api/embed`` response
  (``parse_embed_response``).

Architectural boundary
──────────────────────
This module depends only on the standard library and ``dnd_assistant.errors``.
It must not import from storage, retrieval, application, CLI, or tool modules.
"""

from __future__ import annotations

import math
from typing import Any

from dnd_assistant.errors import ModelError, ValidationError

# ── Caller-input validation ────────────────────────────────────────────────


def validate_embed_inputs(texts: object) -> list[str]:
    """Validate caller-provided embedding inputs before any HTTP request.

    Requires:

    * ``texts`` is a ``list``.
    * ``texts`` is non-empty.
    * Every element is a ``str``.

    Returns the validated list unchanged (no stripping, deduplication,
    normalisation, or other alteration).

    Raises:
        ValidationError: If any requirement is violated.
    """
    if not isinstance(texts, list):
        raise ValidationError(f"embed() requires a list of strings, got {type(texts).__name__}")

    if not texts:
        raise ValidationError("embed() requires at least one text string, got an empty list")

    for i, item in enumerate(texts):
        if not isinstance(item, str):
            raise ValidationError(
                f"embed() item at index {i} must be a string, got {type(item).__name__}"
            )

    return texts


# ── Payload builder ────────────────────────────────────────────────────────


def build_embed_payload(
    *,
    model: str,
    texts: list[str],
    keep_alive: str | None,
) -> dict[str, Any]:
    """Build the Ollama ``POST /api/embed`` JSON payload.

    The ``input`` field is always a JSON array, even for a single text.
    ``truncate`` is explicitly set to ``False`` to prevent silent content loss.
    No generation-only settings (``temperature``, ``options``, ``stream``,
    ``format``, ``tools``, ``think``, ``dimensions``) are included.

    Args:
        model: The configured model name.
        texts: Validated input texts (already confirmed as ``list[str]``).
        keep_alive: Optional keep-alive duration from the profile.

    Returns:
        A JSON-serialisable dict ready for ``httpx.Client.post(json=...)``.
    """
    payload: dict[str, Any] = {
        "model": model,
        "input": texts,
        "truncate": False,
    }

    if keep_alive is not None:
        payload["keep_alive"] = keep_alive

    return payload


# ── Response parsing ───────────────────────────────────────────────────────


def parse_embed_response(
    data: object,
    *,
    expected_count: int,
) -> list[list[float]]:
    """Parse and validate an Ollama ``/api/embed`` response body.

    Validates:

    * Top-level response is a JSON object.
    * ``embeddings`` field exists and is a list.
    * Cardinality: exactly ``expected_count`` vectors.
    * Each vector is a non-empty list.
    * All vectors have the same non-zero length.
    * Every scalar is a JSON numeric (``int`` or ``float``, not ``bool``).
    * Every scalar is finite (not NaN, +Inf, -Inf).

    ``int`` values are converted to ``float`` so the returned type is
    ``list[list[float]]``.

    Provider metadata fields (``model``, ``total_duration``, etc.) are
    silently ignored.

    Raises:
        ModelError: If any validation requirement is violated.
    """
    # ── Top-level structure ────────────────────────────────────────────
    if not isinstance(data, dict):
        raise ModelError(f"Ollama embed response must be a JSON object, got {type(data).__name__}")

    if "embeddings" not in data:
        raise ModelError("Ollama embed response missing 'embeddings' field")

    embeddings = data["embeddings"]
    if not isinstance(embeddings, list):
        raise ModelError(
            f"Ollama embed response 'embeddings' must be a list, got {type(embeddings).__name__}"
        )

    # ── Cardinality ────────────────────────────────────────────────────
    if len(embeddings) != expected_count:
        raise ModelError(
            f"Ollama embed returned {len(embeddings)} vectors for {expected_count} input(s)"
        )

    # ── Per-vector validation ──────────────────────────────────────────
    result: list[list[float]] = []
    first_dim: int | None = None

    for i, vec in enumerate(embeddings):
        _validate_vector(vec, index=i)

        # Convert to float and check finite
        float_vec: list[float] = []
        for j, scalar in enumerate(vec):  # type: ignore[union-attr]
            _validate_scalar(scalar, vector_index=i, element_index=j)
            float_vec.append(float(scalar))  # type: ignore[arg-type]

        # Dimension consistency
        dim = len(float_vec)
        if first_dim is None:
            first_dim = dim
        elif dim != first_dim:
            raise ModelError(
                f"Ollama embed returned inconsistent dimensions: "
                f"vector 0 has {first_dim} elements, "
                f"vector {i} has {dim} elements"
            )

        result.append(float_vec)

    return result


def _validate_vector(vec: object, *, index: int) -> None:
    """Validate a single embedding vector structure.

    Raises ``ModelError`` if the vector is not a non-empty list.
    """
    if not isinstance(vec, list):
        raise ModelError(
            f"Ollama embed vector at index {index} must be a list, got {type(vec).__name__}"
        )
    if not vec:
        raise ModelError(f"Ollama embed vector at index {index} is empty")


def _validate_scalar(value: object, *, vector_index: int, element_index: int) -> None:
    """Validate a single embedding scalar value.

    Accepts ``int`` and ``float`` (excluding ``bool``, which is a subclass
    of ``int`` in Python).  Rejects non-finite floats.

    Raises ``ModelError`` for invalid values.
    """
    # bool is a subclass of int — reject it explicitly
    if isinstance(value, bool):
        raise ModelError(
            f"Ollama embed vector [{vector_index}][{element_index}] is a bool, "
            f"expected a numeric value"
        )

    if isinstance(value, int | float):
        if not math.isfinite(value):
            raise ModelError(
                f"Ollama embed vector [{vector_index}][{element_index}] is not finite: {value!r}"
            )
        return

    raise ModelError(
        f"Ollama embed vector [{vector_index}][{element_index}] "
        f"must be a numeric value, got {type(value).__name__}"
    )
