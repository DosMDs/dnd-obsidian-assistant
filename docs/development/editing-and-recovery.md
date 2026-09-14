# Editing and recovery

Read this when mutating repository text, when an edit/write tool fails, or when
navigating code before editing. The recovery policy is
[ADR-0002](../adr/0002-agent-file-edit-recovery-policy.md).

## 1. Structured editing first

Mutate repository text through OpenCode's structured `edit` / `write` /
`apply-patch` facilities. Shell is not an editor.

The following are repository file mutation and are prohibited without explicit
approval of the shell-fallback exception in §9:

```text
python -c "...open(..., 'w').write(...)"
python -c "...open(..., 'a').write(...)"
python -c "...Path(...).write_text(...)"
python -c "...Path(...).open(...).write(...)"
python <temporary-generator-script>.py
PowerShell Set-Content / Add-Content / Out-File
System.IO.File write APIs
cmd /c "... > file"
shell > file / shell >> file
heredoc/here-string redirected into repository files
base64 decode into repository files
sed / perl bulk mutation
temporary generator scripts used to bypass edit/write limitations
```

It does not matter whether the operation creates, overwrites, appends, patches,
inserts or rewrites the file. If repository content is changed through a
shell-executed Python, PowerShell, Bash, cmd, Node, Perl, Ruby or similar
process, it is shell-based file mutation. `python -c`/`python script.py` are
allowed for non-mutating diagnostics.

## 2. Large edits do not justify another tool

None of the following are valid reasons to switch to shell/Python file writes:

```text
file is large / test file is large
JSON payload was rejected
write payload was too long
edit tool timed out
transport error occurred
a previous edit partially succeeded
many tests must be added
appending text looks easier
```

These require incremental structured editing instead.

## 3. Navigation before editing

Use the smallest sufficient context:

```text
search
→ LSP definitions / references / symbols for code navigation
→ targeted reads of relevant regions
→ structured edit
```

Prefer LSP definitions/references/symbols over broad code scanning, and read
only the relevant sections of large files. Do not globally read large
documents. LSP is navigation/semantic intelligence only, not a correctness gate
(a successful LSP query does not prove runtime correctness, and a Pyright
diagnostic is not a release blocker unless a separate project decision says
so).

## 4. Mandatory incremental-edit procedure

Before changing a large file: read the relevant region, identify exact
logical insertion/replacement points and unique stable anchors, and plan several
small edits. Do not start by generating the complete final file as one giant
payload.

### Existing file

```text
DO:
    read the affected region
    locate a unique nearby anchor
    replace or insert one logical unit
    re-read the changed region
    continue with the next logical unit

DO NOT:
    reconstruct the whole file
    blindly append everything to EOF
    replace unrelated sections
    assume previous edit state after a failed operation
```

A logical unit is one import group, helper, class, protocol method, test class,
parametrized matrix, documentation subsection, public export block or
status-record subsection.

### New large file

Create it incrementally: skeleton (docstring, imports, minimal helper), then one
logical section per operation. Do not create a several-hundred-line file in one
`write` call when smaller sections are safe.

## 5. Patch-size reduction

If a create/edit/patch fails for payload size, parsing, timeout or transport:

```text
DO NOT change tools.
1. re-read the target region;
2. inspect git diff for already-applied content;
3. preserve correct partial work;
4. retry the same logical change with a smaller patch;
5. if it still fails, split that patch again;
6. repeat until each operation is reliably accepted.
```

Use "one logical section per edit". If one logical section is still too large,
divide it by structure (helpers → parametrized normal cases → ambiguity →
validation → error-propagation), never in the middle of a statement.

## 6. Anchors

Use stable, local, unique context: function/class declaration, section heading,
existing test name, `__all__` block or specific adjacent lines. Do not use an
ambiguous one-line anchor. If the tool reports an anchor missing or ambiguous,
re-read the region and choose a more specific anchor — do not switch to shell
mutation.

## 7. Never blindly append

Blind append-to-EOF is prohibited for source and test files when the content
logically belongs inside an existing section/class/module structure. This
includes shell `open(path, "a").write(...)`, `Add-Content`, `>>`, and equivalent
structured edits that dump unrelated code at EOF.

## 8. Test-file construction

Build large pytest files in this order where applicable:

```text
shared fixtures/helpers
→ small reusable fakes/stubs
→ parametrized normal cases
→ special ambiguity/boundary cases
→ validation/error cases
→ integration/protocol regressions
```

Prefer `pytest.mark.parametrize`, helpers, fixtures and small factories to reduce
mechanical duplication. Do not reduce acceptance coverage to make a file
smaller, and do not create hundreds of repeated bodies when a parametrized
matrix expresses the same behavior clearly.

## 9. Recovery and verification

After each substantial logical section, re-read the changed region. After a few
operations, inspect `git diff -- <file>`. Before moving to another file, verify
no duplicate imports/classes/functions/tests, misplaced content, truncation,
missing closing syntax, repeated sections, partial-edit fragments or unrelated
edits.

If an edit partially succeeded:

```text
read current file
git diff -- <file>
identify what actually landed
preserve correct content
remove only broken/duplicated fragments
continue from current state with a smaller edit
```

Never repair a partial file by wholesale overwrite unless a full-file replacement
is genuinely the smallest safe operation the structured tool can perform
reliably. Run the narrowest useful validation once a coherent unit exists (e.g.
`uv run ruff check <file>`, `uv run pytest <relevant-test-file>`).

## 10. Shell-fallback exception

If structured file tools are genuinely unavailable or objectively cannot perform
the operation independent of payload size: **STOP**, explain the exact limitation
to the user, and request explicit approval for shell-based mutation. Without
approval, do not execute repository-writing shell commands. A payload being too
large is explicitly not an exception.

## 11. Final check and shell use

Before claiming implementation complete:

```text
git status
git diff --check
git diff
```

Review the complete task diff for truncation, duplicated code, append artifacts,
generated temporary files, unrelated changes, and repository files written
through prohibited shell fallback.

Shell remains normal and expected for development commands:

```text
uv
pytest
ruff
git
diagnostics
project CLI
```

Save all project text files as UTF-8.
