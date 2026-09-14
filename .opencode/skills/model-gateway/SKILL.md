---
name: model-gateway
description: Implement or review provider-neutral ModelGateway contracts, Ollama adapters, model profiles, structured output, tool calls, health and provider errors.
---
# Model gateway

Read [current status](../../../DEVELOPMENT_STATUS.md), [Stage 8](../../../docs/stages/08_MODEL_GATEWAY_AND_OLLAMA.md), accepted gateway/profile DTOs and adapter tests. For framework replacement also load [PAIM guidance](../pydantic-ai-migration/SKILL.md).

Keep provider URL/model/quantization/timeouts/payload details in configuration/adapters, separate from provider-neutral application contracts. Separate native provider metadata (e.g. Ollama `created_at`, `eval_count`, `load_duration`) from provider-neutral DTOs. Validate structured output before application use and map network/provider failures into project model errors at the owning boundary.

Provider responses are untrusted even from localhost. Derive field equivalence classes: missing, null, expected/wrong empty containers, empty string, 0, False, True, valid and malformed non-empty values. Presence is not truthiness, so do not use `if value:` to infer presence or validity. Reject bool where numeric-only, reject non-finite floats and contain integer-to-float overflow. Review parsing/coercion/indexing/library exception containment using [untrusted-boundaries](../../../docs/development/untrusted-boundaries.md) and [quality policy](../../../docs/development/quality-and-evidence.md).

Mock HTTP with respx for ordinary tests; real Ollama is separately authorized opt-in smoke. Test structured/tool payloads, malformed falsy values, native-metadata separation and error mapping. Benchmark/eval results determine model selection, not opinion; this skill does not authorize new model defaults, timeout changes or live measurement.

Stop on missing pinned public API evidence, incompatible project contracts, unauthorized dependencies or attempts to broaden production validation for a weak wrapper/double. Report limitations and follow PAIM qualification rather than private framework patches.
