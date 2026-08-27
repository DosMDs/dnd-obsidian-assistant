---
name: model-gateway
description: Implement or review ModelGateway, OllamaProvider, model profiles, structured outputs, tool calling, provider errors or health checks.
compatibility: Python 3.12+, httpx, Pydantic, respx, optional Ollama.
metadata:
  version: "1"
---
# Model gateway and Ollama

1. Depend on a provider-neutral ModelGateway contract from application code.
2. Keep Ollama URL, model names, quantization, timeouts and provider payload details inside configuration/provider code.
3. Validate structured model outputs with Pydantic before application use.
4. Treat model text/tool calls as untrusted input.
5. Map network/provider errors into project-level model errors.
6. Mock HTTP behavior in the normal test suite with respx.
7. Keep real Ollama tests opt-in smoke tests.
8. Do not select a default fast/heavy model by opinion; model choice belongs to benchmark/eval results.
