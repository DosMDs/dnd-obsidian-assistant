# Provider / runtime upgrade runbook

Operational maintenance procedure for changing the Pydantic AI runtime,
the Ollama runtime, or model/profile configuration. This is a future-facing
runbook, not migration history. Historical Pydantic AI migration evidence lives
in `docs/migrations/001_PYDANTIC_AI_RUNTIME.md` and
`docs/adr/0003-pydantic-ai-runtime-migration.md`.

The project owns policy and consequences; Pydantic AI and Ollama are
replaceable mechanisms. Framework tool exposure/filtering/approval is **not**
an authorization boundary. Every side effect still flows through
`DndAgentPolicy` → `PydanticAIToolExecutor` (`ToolExecutor`) → application /
`VaultRepository`.

## 1. Scope and vocabulary

This runbook applies when a change touches any of:

- the Pydantic AI package family resolved through `uv.lock`;
- the Ollama runtime binary;
- a model/profile value that changes provider behavior.

It does **not** apply to ordinary product work that merely happens to live in a
repository containing Pydantic AI.

## 2. Trigger classes

| Class | Trigger | Notes |
|---|---|---|
| U1 | Pydantic AI framework/package change (`pydantic-ai-slim`, `pydantic-ai`, `pydantic-graph`, or directly coupled OpenAI client changes produced by lock resolution) | Provider integration may have changed |
| U2 | Ollama runtime binary change | No Python dependency bump may occur |
| U3 | model / profile change (model tag, temperature, timeout, role profile, base-URL semantics) | Config-only; may accompany U1/U2 or stand alone |
| U4 | no provider/runtime-related change | No special gate required |

A change is only a U4 when it touches none of the U1–U3 surfaces. The existence
of Pydantic AI in the repository is not by itself a trigger.

## 3. Baseline capture (before any change)

```text
clean working tree
exact starting SHA
exact current direct pin (pyproject.toml)
exact accepted/current runtime versions (uv.lock for Python; external for Ollama)
uv lock --check
```

Record the accepted/current version of every affected component. For Ollama,
record the runtime version as **external evidence** (e.g. `/api/version`); it is
never derivable from `pyproject.toml` or `uv.lock`.

## 4. Authoritative upstream review

Before changing a pin or runtime, review the authoritative sources and record
the result for each relevant theme.

Sources:

```text
Pydantic AI
  https://github.com/pydantic/pydantic-ai/releases
  https://ai.pydantic.dev/changelog/         (canonical changelog)
  https://ai.pydantic.dev/upgrade/           (upgrade guide, when present)

Ollama
  https://github.com/ollama/ollama/releases
  native endpoints /api/version, /api/tags (already read by the live gate)
```

Recorded review fields (required):

```text
accepted/current version
candidate version
review date
authoritative release/changelog source
reviewed range (accepted .. candidate)
relevant compatibility / breaking notes
relevant issue references
unresolved upstream risks
```

Targeted themes to review rather than "read all issues":

```text
tools / toolsets / exposure preparation
DeferredToolRequests / DeferredToolResults
HandleDeferredToolCalls / capability behavior
Agent.run_sync
UsageLimits
tool retries / output retries
parallel vs sequential tool execution
worker-thread behavior
OllamaProvider / OllamaModel
OpenAI-compatible tool messages
structured output / ToolOutput
exception / error mapping
```

Classification per theme: `REVIEWED`, `NOT APPLICABLE`, `OPEN RISK`.

Do not encode a specific "latest" version as policy. Versions recorded by a
past review are dated evidence only; a new upgrade re-runs this review.

## 5. Candidate isolation

- Start from a clean worktree and an ordinary forward task branch.
- Change only the intended direct pin, profile value, or runtime input.
- Do not bundle unrelated dependency upgrades.
- Do not edit `uv.lock` by hand.

## 6. pyproject / profile diff

Review the exact diff of `pyproject.toml` and any configuration/profile change.
For U3, the diff is config-only and must not silently pull a package change.

## 7. uv lock workflow

Supported command shapes (narrowest first):

```text
uv lock --upgrade-package <name>     # update one package's resolution
uv lock                              # reconcile after a pin edit
uv lock --check                      # verify the lock is up to date
```

Then classify every `uv.lock` change:

```text
TARGET                the intended package (and its direct metadata)
REQUIRED_TRANSITIVE   a legitimate consequence of the target change
UNRELATED             anything else
```

Any `UNRELATED` upgrade blocks acceptance until justified or removed. Do not
require a byte-identical lock outside the expected dependency closure;
transitive changes can be legitimate.

## 8. Offline curated gate

```text
uv run pytest -m "provider_upgrade and not ollama"
```

This selection is deterministic, offline and requires no running Ollama, no
internet and no secrets. It is the curated Pydantic AI / provider / runtime
regression gate. Its reviewed inventory is protected by
`tests/contract/test_provider_upgrade_gate.py`.

For a U3 profile change, also run the profile/provider tests it affects
(provider factory, composition, profile validation) even if they are outside
the marker selection.

## 9. Static / repository gates

```text
uv run pyright
uv run ruff check .
uv run ruff format --check .
git diff --check
```

## 10. Canonical suite

```text
uv run pytest
```

One canonical run after focused/affected/static gates are stable. Follow
`docs/development/quality-and-evidence.md` for failure-loop and rerun policy.

## 11. Live compatibility gate

Mandatory for every applicable U1/U2 (and for U3 where provider interaction is
involved):

```text
uv run pytest -m "provider_upgrade and ollama"
```

Semantics:

- absent live configuration → skip **before** any network access;
- set-but-invalid configuration (missing file, missing profile, wrong provider,
  unreachable endpoint, missing model) → fail, never silently skip.

The two live modules have distinct roles:

```text
integration/test_pydantic_ai_ollama_smoke.py
    standalone OllamaModel/OllamaProvider + real structured output
integration/test_pydantic_ai_ollama_live_runtime.py
    production factory/runtime + real tool continuation
```

Do not add latency or product-quality thresholds here. Those belong to the
S14-07 baseline.

## 12. Post-S14-07 model-quality gate handoff

Once the accepted S14-07 product live eval / frozen baseline exists, a U3
model/profile qualification **also** requires that accepted S14-07 product live
eval / baseline comparison. Until then, the live gate proves runtime
compatibility, not model-quality acceptance.

## 13. Outcome classification

### ACCEPTED

```text
intended version/profile diff only
required upstream changes reviewed
lock diff classified (no unresolved UNRELATED)
offline curated gate green
static/repository gates green
canonical suite green
required live gate green
no architecture/safety regression
HEAD/upstream evidence complete
```

### BLOCKED

```text
required live environment unavailable when live evidence is mandatory
unresolved upstream risk
candidate cannot be tested
unresolved unrelated lock changes
```

BLOCKED is not a failed product candidate; it is incomplete evidence.

### REJECTED

The candidate demonstrably violates a project invariant or required runtime
behavior. Record exactly:

```text
candidate version
failing invariant
minimal reproducible failing test
observed error
whether the failure is framework/provider/model-specific
rollback result
```

### SKIPPED_CAPABILITY

Only for a genuinely unavailable capability that this runbook explicitly marks
non-blocking. Never use it to hide a required provider smoke for an upgrade
that is being accepted.

## 14. Rollback / rejection

```text
ordinary forward task branch
small version/profile diff
no history rewrite
revert the candidate diff, or abandon the task branch
```

Git is the rollback mechanism. Do not keep a permanent dual runtime and do not
add a fallback-provider feature flag merely to accommodate an incompatible
upgrade.

## 15. Final evidence checklist

```text
baseline SHA and clean start
accepted version -> candidate version
review date and authoritative sources
reviewed range and compatibility notes
pyproject.toml diff
uv.lock diff classified TARGET / REQUIRED_TRANSITIVE / UNRELATED
offline curated gate result
canonical suite result
live gate result (or explicit BLOCKED reason)
outcome classification
HEAD == upstream and clean worktree
```
