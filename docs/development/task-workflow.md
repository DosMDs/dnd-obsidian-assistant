# Task workflow

Durable workflow contract for development tasks. Read this for stage, multi-file,
migration, correction or Git-finalization work. Quality-gate selection and
evidence rules live in [quality-and-evidence.md](quality-and-evidence.md).

## 1. Task kickoff and status authority

- Read `DEVELOPMENT_STATUS.md` before planning implementation work; it is the
  canonical source for the current stage, task and migration state.
- Historical chats, context snapshots and old Final Reports may contain
  historical snapshots. Do not use them as current status when they conflict
  with `DEVELOPMENT_STATUS.md`.
- Work within the current roadmap stage unless the user explicitly changes
  scope.
- Never automatically begin the next roadmap task or stage after completing the
  current one.
- Do not mark a task or stage `DONE` merely because code was generated.
  Completion requires the requested implementation/documentation, relevant
  checks, final diff review and (when required) commit/push/upstream
  verification.
- Record significant architectural/workflow decisions as ADRs under
  `docs/adr/`. Git commits record concrete changes; Git tags record completed
  milestones.

## 2. Starting-state capture

Before modifying a task:

- capture starting HEAD (commit SHA), branch name and `git status --short`;
- identify the expected/allowed file scope from the task description.

A dirty working tree must not be silently absorbed into the task. Pre-existing
changes must be identified, classified and preserved unless the task explicitly
authorizes restoration or removal. Never silently discard pre-existing changes.

## 3. Owning layer and intended diff

Every task has an **intended diff** — the set of files it is expected to create
or modify.

- Identify the owning architectural layer and the intended change surface before
  editing. Do not invent missing APIs when repository evidence can answer the
  question; inspect the code first.
- Before commit, derive the actual changed-file list from Git
  (`git status --short`, `git diff --name-status`, `git diff --stat`, `git diff`)
  and compare it against the intended scope.
- Inspect every unexpected changed file. Required decision:
  `required for root cause?` → yes: classify/document the scope expansion;
  no: remove the unintended edit.
- Never silently widen scope.

## 4. Scope control

Make the smallest coherent change and stay within the authorized task scope. If
an unrelated defect or missing feature is discovered:

- document the discovery;
- do not automatically fix it;
- report it to the user for prioritization.

Do not absorb unrelated work into the current task.

## 5. PLAN vs BUILD behavior

- Investigate before mutating: inspect relevant docs, code and tests.
- Use planning/read-only behavior for multi-file, architectural, migration,
  storage or otherwise risky changes before editing.
- Once a plan is authorized, BUILD implements that exact plan; do not silently
  broaden or re-scope it.

Approval is required before destructive Git operations, modifying a real
campaign Vault, deleting data, irreversible migrations, changing
credentials/secrets, enabling unrestricted MCP filesystem/shell tools, and
publishing/releasing. Never read or modify `.env` or credential/token files
unless the user explicitly requests a safe configuration task.

## 6. Git finalization

When a Task Contract requires normal Git finalization, after all changes and
required gates are complete:

```text
run gates
→ stage only task files
→ one coherent commit
→ ordinary push
→ verify HEAD == upstream
→ clean task-owned working tree
→ stop repository mutations
```

- Before the task commit, run or follow the `pre-finalization-audit` skill. The
  final changed-file inventory must come from Git, not from memory. A mandatory
  failed test or Ruff gate means no push.

- An authorized Task Contract is the confirmation; ordinary `git commit` and
  `git push` do not require a second confirmation and do not require interactive
  approval merely because they are Git.
- Do not push if required tests, Ruff or other mandatory checks have not passed.
- Keep all task changes (sources, tests, status, stage docs, ADRs) ready before
  the intended task commit.
- After the task commit, do not edit docs to insert the new SHA, amend for a
  self-SHA, or create a second status-only/self-SHA commit. The commit SHA
  belongs in the Final Report; repository docs should use
  `(reported in Final Report)` or omit the current task SHA.
- Use Conventional Commits, e.g. `feat: …`, `fix: …`, `test: …`,
  `docs: …`, `refactor: …`.

Never, without explicit architecture/user authorization:

```text
git push --force / --force-with-lease
git reset --hard
published-history rewrite
destructive rebase
destructive branch deletion / git clean
```

If an ordinary push is rejected, stop and report the reason.

## 7. Correction lifecycle

- A correction pass fixes a confirmed defect in the owning layer and adds
  regression coverage where practical.
- If the same task requires two or more correction passes for the same class of
  problem, stop and perform a meta-review before adding another local
  workaround: identify the repeated defect pattern, the missing reusable
  invariant, and update the relevant rule/skill/helper before continuing.
- Do not make a gate pass by weakening a threshold, allowlist or safety
  boundary. See [maintainability.md](maintainability.md).
