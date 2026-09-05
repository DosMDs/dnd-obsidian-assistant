# Pydantic AI migration — mandatory architecture rule

This rule applies to every `PAIM-*` task and any later work that touches Pydantic AI, agent runtime replacement, framework toolsets, framework model/provider integration, or removal of the custom Fast Agent runtime.

## 1. Framework role

Pydantic AI is **replaceable infrastructure**.

It may own generic agent/model/tool protocol mechanics, but it must not become the owner of campaign/domain truth, authorization or filesystem consequences.

## 2. Non-negotiable project boundaries

Do not move these responsibilities into framework code:

```text
Domain schemas/rules
VaultRepository
CalendarService
Retrieval/EntityResolver policy
Session raw-log invariants
ToolRegistry application metadata
ToolExecutor
permissions/session modes/audit prerequisites
ChangeSet apply policy
```

`domain/` and `storage/` must not depend on Pydantic AI or Ollama.

## 3. Tool execution boundary

Framework tool exposure/filtering/approval is NOT authorization.

Every tool side effect must flow through the existing trusted boundary:

```text
framework tool adapter
→ ToolExecutor
→ application/domain service
→ VaultRepository
```

Direct framework-decorated write handlers that mutate the Vault or call repository writes while bypassing `ToolExecutor` are prohibited.

## 4. Fail-closed policy

Malformed/unexpected framework/model data must not gain more authority.

Explicitly preserve fail-closed behavior for:

- unknown tool names;
- hidden tools;
- malformed exposure snapshots;
- malformed permission/session data;
- invalid call IDs;
- invalid tool arguments;
- forbidden write/mixed batches;
- unexpected second-round tool calls.

Do not rely on Python truthiness or permissive enum/string equality at untrusted boundaries.

## 5. Stage-9 behavioral invariants

Before replacing/removing custom runtime behavior, prove equivalent behavior for:

```text
frozen turn-local exposure
bounded model requests
bounded tool calls
complete batch preflight
READ-only accepted multi-call batch
reject forbidden batch before first execution
sequential accepted batch execution
WRITE audit requirement
duplicate call-ID fail-close
explicit retry policy
terminal second-response policy
clarification over speculative write
```

Framework defaults do not override these invariants.

## 6. Retry policy

Do not accept automatic framework retry behavior implicitly.

Separate and reason about:

```text
semantic/tool retry
structured-output retry
transport retry
```

A retry around a side-effecting operation requires explicit exactly-once/idempotency reasoning and tests.

## 7. Sync/thread behavior

Treat framework worker-thread execution of sync tools as an explicit boundary risk.

Before accepting it, test:

- ToolExecutor exactly-once behavior;
- audit/context propagation;
- VaultRepository/file operations;
- SQLite connection/thread assumptions;
- ContextVar/thread-local assumptions;
- exception mapping.

Do not redesign trusted domain/storage simply to accommodate a framework default without architecture review.

## 8. Ollama

Do not delete the native/custom Ollama implementation until framework Ollama behavior passes the dedicated comparison gate.

A selective custom Ollama model/provider component is allowed in a `PARTIAL` migration.

## 9. No permanent dual runtime

The fallback/reference is `main`/Git history, not a permanent production feature flag.

Short-lived comparison code/tests are allowed for qualification, but the migration branch must remove superseded equal-status production runtime code before final acceptance.

## 10. Framework limitation workflow

When a mismatch is discovered:

```text
reproduce with focused test
→ identify exact project invariant
→ try documented public extension point
→ evaluate small selective custom component
→ if still fragile/large, stop and propose REJECTED outcome
```

Do not patch private framework internals as the default solution.

Document framework limitation and evidence in `docs/migrations/001_PYDANTIC_AI_RUNTIME.md`.

## 11. Dependency/version policy

- Do not add or upgrade Pydantic AI casually.
- Candidate version must be explicit in qualification evidence.
- Review `pyproject.toml` and `uv.lock` diffs.
- Do not mix unrelated dependency upgrades into PAIM tasks.
- Later framework upgrades are standalone maintenance tasks.

## 12. Scope guard

PAIM does not authorize unrelated additions such as vector DB, LangChain/LlamaIndex/Haystack, web UI, graph DB, voice, LoRA, workflow engines, DI frameworks or broad storage refactors.
