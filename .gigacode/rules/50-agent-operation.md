---
apply: ALWAYS
mode: AGENT
---
# Agent operating policy

Before modifying code:
- inspect relevant code and tests;
- identify architectural layer and roadmap stage;
- use Plan Mode for multi-file, architectural, migration or risky changes.

During work:
- keep the diff focused;
- do not rewrite unrelated files;
- do not add dependencies casually;
- do not weaken validation or safety boundaries for convenience.

Require explicit user approval before:
- destructive Git operations;
- modifying a real campaign Vault;
- deleting data;
- running migrations with irreversible effects;
- changing credentials/secrets;
- enabling unrestricted MCP filesystem/shell tools;
- pushing, publishing or releasing.

Never read or modify `.env`, credential/token files unless the user explicitly requests a safe configuration task.
