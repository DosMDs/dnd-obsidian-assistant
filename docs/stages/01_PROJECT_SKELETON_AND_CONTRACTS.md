# Stage 1 — Project skeleton + contracts

## Objective

Create explicit package boundaries and common project contracts before domain/storage implementation begins.

This stage deliberately contains **no LLM runtime implementation** and **no Vault persistence implementation**.

## Inputs

- project architecture and boundaries;
- implementation roadmap;
- accepted engineering decisions;
- `DEVELOPMENT_STATUS.md`;
- `GIGACODE.md`.

## Expected package areas

```text
src/dnd_assistant/
├── cli/
├── application/
├── domain/
├── storage/
├── retrieval/
├── tools/
├── models/
├── prompts/
└── evals/
```

Tests:

```text
tests/
├── unit/
├── integration/
├── contract/
├── e2e/
└── fixtures/
```

## Interface inventory

The project is expected to expose clear boundaries for:

- `ModelGateway`
- `VaultRepository`
- `SearchService`
- `EntityResolver`
- `CalendarService`
- `SessionService`
- `ToolRegistry`
- `ToolExecutor`
- `PostSessionProcessor`
- `BootstrapService`
- `AuditService`

### Rule for signatures

Do not invent weak placeholder types simply to finish the inventory.

If a final method signature depends on a domain concept that is intentionally introduced in Stage 2, document the responsibility here and complete the typed signature together with that domain concept.

## Shared errors

Target hierarchy:

```text
DndAssistantError
├── ValidationError
├── NotFoundError
├── ConflictError
├── AmbiguousEntityError
├── StorageError
├── ModelError
└── LockError
```

Use project errors at architectural boundaries rather than leaking provider/library-specific exceptions into callers.

## Dependency direction

Forbidden examples:

```text
domain -> OllamaProvider
storage -> OllamaProvider
domain -> CLI
storage -> CLI
CalendarService -> LLM
```

Expected orchestration direction:

```text
CLI
 ↓
Application
 ├── domain/service contracts
 ├── retrieval contracts
 ├── storage contracts
 └── ModelGateway contract (later implementation)
```

## Task breakdown

### CTR-001 — Package skeleton

Verify/create importable packages and `__init__.py` files where required.

Do not add placeholder business logic.

### CTR-002 — Error hierarchy

Implement common project errors in a provider-neutral module.

Add unit tests for hierarchy/catch behavior where useful.

### CTR-003 — Core contracts

Create the boundary modules/protocols that can be expressed honestly at this stage.

Prefer `typing.Protocol` when structural interfaces are useful and there is no need for inherited implementation.

Do not introduce a dependency solely to enforce interfaces.

### CTR-004 — Responsibility documentation

Each core interface/module should state:

- what it owns;
- what it must not own;
- which layer may call it;
- expected failure boundary.

### CTR-005 — Contract/import tests

Add tests that verify:

- expected modules import;
- no Ollama/provider import is required for domain/storage import;
- normal pytest collection does not need an Ollama service.

### CTR-006 — Boundary review

Review imports and ensure provider-specific details remain outside domain/storage.

### CTR-007 — Quality gates

Run:

```text
uv run pytest
uv run ruff check .
uv run ruff format --check .
```

### CTR-008 — Completion record

Review the diff, update `DEVELOPMENT_STATUS.md`, and commit the completed stage/task increment.

## Out of scope

Do not implement yet:

- Entity/Pydantic domain schemas beyond what is necessary for an honest shared error/contract;
- Vault Markdown/YAML persistence;
- atomic writes;
- calendar arithmetic;
- search/FTS;
- sessions;
- ToolExecutor behavior;
- OllamaProvider;
- agent loops;
- ChangeSet.

## Definition of Done

See `DEVELOPMENT_STATUS.md`. That file is the canonical current status source.
