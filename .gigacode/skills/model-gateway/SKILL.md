---
name: model-gateway
description: Implement or review ModelGateway, OllamaProvider, model profiles, structured outputs, tool calling, provider errors or health checks.
compatibility: Python 3.12+, httpx, Pydantic, respx, optional Ollama.
metadata:
  version: "2"
---
# Model gateway and Ollama

## Provider-neutral architecture

1. Depend on a provider-neutral ModelGateway contract from application code.
2. Keep Ollama URL, model names, quantization, timeouts and provider payload details inside configuration/provider code.
3. Validate structured model outputs with Pydantic before application use.
4. Treat model text/tool calls as untrusted input.
5. Map network/provider errors into project-level model errors.
6. Mock HTTP behavior in the normal test suite with respx.
7. Keep real Ollama tests opt-in smoke tests.
8. Do not select a default fast/heavy model by opinion; model choice belongs to benchmark/eval results.

## Provider response validation

Provider responses must be treated as **untrusted external input** even when
they come from localhost.

### Structural field matrix

For provider-owned fields, where applicable, test/review:

```text
missing
None
[]
{}
""
0
False
True
valid value
malformed non-empty value
```

Derive equivalence classes from the contract; do not test only happy path
plus one arbitrary malformed value.

### Truthiness prohibition for structural validation

Do not use `if value:` to decide whether a provider-supplied field is
present or valid. Use explicit presence checks such as:

```python
if "field" in data:
    ...
```

See `.gigacode/rules/09-untrusted-boundary-validation.md` for the full
structural-field equivalence-class policy.

### Numeric provider boundaries

Provider responses may contain numeric values that trigger Python edge
cases:

```text
bool is a subclass of int
NaN / +Infinity / -Infinity are valid floats
oversized integers may overflow int -> float conversion
```

Reject non-finite floats, reject bool where int is expected, and handle
conversion overflow explicitly.

### Public exception containment

Provider adapters are public boundaries. Review incidental exceptions from:

```text
JSON decoding
field access / indexing
type coercion
numeric conversion
mapping to DTOs
```

Each must be intentionally handled: wrapped in a project error, returned as
validated state, or documented as a programming error.

### Native provider metadata vs provider-neutral DTOs

Provider-native response metadata (e.g. Ollama `created_at`, `eval_count`,
`load_duration`) must be separated from provider-neutral DTO content at the
adapter boundary. Do not leak provider-specific fields into application
contracts.

### Normal mocked HTTP vs opt-in real-provider tests

- Normal tests: mock HTTP with respx.
- Real-provider tests: opt-in only, explicitly marked, not part of the
  default test suite.
