---
name: implement-feature
description: Implement a scoped D&D Assistant application feature or roadmap slice across existing Python contracts, modules and tests.
---
# Implement feature

Read [current status](../../../DEVELOPMENT_STATUS.md), the applicable stage/migration/ADR, existing production contracts and nearby tests. Resolve task baseline and acceptance mapping per [task-workflow](../../../docs/development/task-workflow.md) and [stage-workflow](../stage-workflow/SKILL.md).

Identify the owner of each responsibility and an intended file inventory. For multi-file or boundary-affecting work plan contracts, files, tests and risks first. Implement the smallest coherent vertical slice using accepted abstractions, with relevant tests in the same change. Keep deterministic policy in trusted Python and composition separate from presentation/provider mechanics.

Run targeted checks, then broader gates required by the final diff/risk under [quality policy](../../../docs/development/quality-and-evidence.md). Required gates must be green, not merely attempted. Use the `.opencode/agents/` reviewer subagents proportionately and finish with [pre-finalization-audit](../pre-finalization-audit/SKILL.md).

Common failures are speculative APIs, business logic in CLI/provider adapters, unrelated dependency upgrades and expanding a feature to later roadmap stages. Stop/report unrelated defects, missing authorization for deferred product scope or protected harness changes. Do not weaken trusted boundaries or ratchets for convenience; commit/push only as separately authorized.
