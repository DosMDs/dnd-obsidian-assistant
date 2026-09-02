# Stage 8 — Model Gateway / Ollama

## Stage objective

Establish the provider-neutral ModelGateway typed contract, implement the
Ollama provider, and integrate it with the existing Tool Layer handshake.

## Architectural boundaries

- ModelGateway is a `typing.Protocol` — concrete providers are replaceable.
- All five canonical operations are synchronous for MVP.
- Provider-neutral DTOs live in `dnd_assistant.models.types` with no
  imports from storage, retrieval, application, CLI, or Ollama.
- `chat_with_tools()` accepts `ToolPublicDefinition` via TYPE_CHECKING-only
  import to keep the gateway module lightweight.
- Provider/network failures surface as `ModelError` (existing in `errors.py`).
- No Fast Agent, no tool execution, no prompt templates in this stage.

## Pre-Stage-8 base

```
9bca669894b2ae12a62381a2f7b6a5447c44e9cd
```

## Sync MVP decision

Stage 1 deferred the sync/async decision until Stage 8.  The Stage-8 MVP
ModelGateway is **synchronous** (`def`, not `async def`).

Rationale:

- Current Typer/application/runtime stack is synchronous.
- Current trusted Python services and ToolExecutor are synchronous.
- httpx already supports synchronous transport.
- Introducing async through the whole application would add complexity
  without an MVP requirement.
- A future async provider/gateway may be added separately without changing
  this MVP contract retroactively.

## Provider-neutral gateway contract

Five canonical synchronous operations:

| Operation | Input | Output |
|---|---|---|
| `chat` | `ChatRequest` | `ChatResponse` |
| `chat_with_tools` | `ChatRequest` + `list[ToolPublicDefinition]` | `ToolAwareResponse` |
| `generate_structured` | `ChatRequest` + `type[T]` (Pydantic) | `T` |
| `embed` | `list[str]` | `list[list[float]]` |
| `health` | — | `ModelHealth` |

## Stage-7 ToolPublicDefinition handshake

`chat_with_tools()` consumes `ToolPublicDefinition` from the Tool Layer
via a `TYPE_CHECKING`-only import in `gateway.py`.  This ensures:

- Runtime import of `dnd_assistant.models.gateway` does not eagerly load
  `dnd_assistant.tools`, storage, retrieval, application, CLI, or Ollama.
- The existing boundary tests (`test_gateway_does_not_import_tools`, etc.)
  continue to pass.

## S8 task map

| Task | Status | Notes |
|---|---|---|
| **S8-00** | **DONE** | Provider-neutral typed ModelGateway contracts + sync decision |
| S8-01 | NOT STARTED | Model profile schemas + machine profile loader |
| S8-02 | NOT STARTED | Ollama transport + health + plain chat |
| S8-03 | NOT STARTED | Ollama structured generation |
| S8-04 | NOT STARTED | Ollama native tool-calling adapter |
| S8-05 | NOT STARTED | Ollama embeddings |
| S8-06 | NOT STARTED | Provider integration / error hardening / opt-in smoke coverage |
| S8-07 | NOT STARTED | Full Stage-8 historical review / completion |

Correction passes:

| Task | Status | Notes |
|---|---|---|
| S8-C00+ | — | Only if required after review |

## Deferred work

The following are explicitly deferred to later S8 tasks:

- Ollama HTTP calls (`/api/chat`, `/api/embed`, etc.)
- Model profile schemas and machine profile loader
- Tool-schema Ollama adapter
- Provider error mapping
- Real Ollama smoke tests

## S8-00 implementation record

### Changed files

- `src/dnd_assistant/models/types.py` — new: provider-neutral DTOs
- `src/dnd_assistant/models/gateway.py` — rewritten: ModelGateway Protocol
- `src/dnd_assistant/models/__init__.py` — updated: public exports
- `tests/unit/test_model_gateway_contracts.py` — new: 64 tests
- `docs/stages/08_MODEL_GATEWAY_AND_OLLAMA.md` — new: this document
- `docs/stages/README.md` — updated: Stage-8 index entry
- `DEVELOPMENT_STATUS.md` — updated: Stage 8 IN PROGRESS

### Quality-gate evidence

- 64 passed (gateway contract tests)
- 97 passed (boundary tests) — zero diff in `test_boundaries.py`
- 284 passed (maintainability tests) — no ceiling changes
- 25 passed (test harness policy tests)
- Full pytest suite: (reported in Final Report)
- Ruff check: (reported in Final Report)
- Ruff format: (reported in Final Report)