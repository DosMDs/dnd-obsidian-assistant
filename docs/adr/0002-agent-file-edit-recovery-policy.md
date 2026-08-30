# ADR-0002: Agent file-edit recovery policy

- **Status:** Accepted
- **Date:** 2026-08-30

## Context

During Stage 2 implementation, GigaCode attempted to create a large
`tests/unit/test_timeline_event.py` file through its built-in `write` tool.

The tool failed while parsing the large JSON payload. The failure was a
transport/tooling problem rather than a problem with the requested
TimelineEvent implementation.

After the failure, the agent proposed switching to Bash and then PowerShell to
generate/write the source file. The repository already preferred built-in
GigaCode/IDE file tools over shell-based editing, but the previous exception
for cases where a file tool was “unable” to perform an operation was too broad.
A payload-size or JSON-transport failure could incorrectly be interpreted as
permission to bypass the normal editing path.

This creates several risks:

- platform-specific development behavior on Windows/macOS;
- accidental truncation or corruption after a partial failed write;
- loss of visibility into already-successful partial edits;
- overly large generated test files instead of compact parametrized tests;
- normalization of shell/file-generation workarounds despite available IDE
  repository-edit tools.

## Decision

Repository text files must be edited with built-in GigaCode/IDE file tools by
default.

A technical edit/write failure such as:

- JSON parsing error;
- oversized/large payload;
- timeout;
- transport failure;

does **not** mean that the built-in file tools are incapable of performing the
task and does **not** authorize an automatic switch to Bash, PowerShell,
Python one-off scripts, base64 generation, shell redirection, or equivalent
source-file generation.

The required recovery sequence is:

```text
edit/write failure
        ↓
inspect current file and working tree
        ↓
preserve correct partial work
        ↓
retry using smaller atomic create/edit/patch operations
        ↓
reduce needless duplication where appropriate
        ↓
verify final diff
```

For large tests, pytest parametrization and helpers should be preferred when
they reduce repetitive test bodies without weakening task acceptance criteria
or regression coverage.

Shell-based file mutation is an explicit exception only when built-in file
tools are genuinely unavailable or objectively cannot support the required
operation independently of payload size.

Before using that exception, the agent must:

1. explain the concrete limitation to the user;
2. obtain explicit approval;
3. limit the fallback to the minimum required file/operation;
4. inspect the final diff afterward.

Shell remains a normal mechanism for development commands such as `uv`,
`pytest`, `ruff`, `git`, CLI execution, and non-mutating diagnostics.

## Implementation

The policy is enforced/documented in:

```text
GIGACODE.md
.gigacode/rules/06-tool-usage.md
09_ENGINEERING_DECISIONS.md
11_DEVELOPMENT_WORKFLOW_GIGACODE_AND_STATUS.md
```

## Consequences

### Positive

- consistent recovery behavior after editor-tool failures;
- less platform-specific shell dependence;
- safer preservation of partial work;
- smaller, more maintainable generated tests;
- fewer accidental source-file rewrites;
- the policy remains visible across future GigaCode runs and ChatGPT project
  conversations.

### Trade-offs

- a failed large write may require several smaller edit operations;
- agents must inspect partial state before retrying;
- rare legitimate shell-based file mutation now requires explicit user
  approval.

## Supersedes

This ADR narrows the fallback exception in the original GigaCode tool-usage
policy. It does not supersede ADR-0001.
