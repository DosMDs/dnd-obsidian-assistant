---

apply: ALWAYS
mode: AGENT
-----------

# Incremental repository file editing

Repository text files must be edited through built-in GigaCode/IDE repository
file tools.

This rule defines the mandatory procedure when an edit is too large for one
reliable file-tool operation.

## 1. Shell is not an editor

The following are repository file mutation and are prohibited unless the user
has explicitly approved the shell-fallback exception defined in
`06-tool-usage.md`:

```text
python -c "...open(..., 'w').write(...)"
python -c "...open(..., 'a').write(...)"
python -c "...Path(...).write_text(...)"
python -c "...Path(...).open(...).write(...)"

python script.py
when script.py is created or used primarily to generate/append/rewrite
repository source/test/documentation files

PowerShell Set-Content
PowerShell Add-Content
PowerShell Out-File
System.IO.File write APIs

cmd /c echo ... > file
shell > file
shell >> file
heredoc/here-string redirected into repository files
base64 decode into repository files
temporary generator scripts used to bypass IDE edit/write limitations
```

It does not matter whether the operation:

```text
creates
overwrites
appends
patches
inserts
or rewrites
```

the file.

If repository content is being changed through a shell-executed Python,
PowerShell, Bash, cmd, Node, Perl, Ruby, or similar process, it counts as
shell-based file mutation.

`python -c` is allowed only for non-mutating diagnostics.

## 2. Large edit does not justify another writing tool

The following are NOT valid reasons for switching to shell/Python file writes:

```text
file is large
test file is large
JSON payload was rejected
write payload was too long
edit tool timed out
transport error occurred
previous edit partially succeeded
many tests must be added
appending text looks easier
```

These conditions require incremental IDE editing instead.

## 3. Mandatory incremental-edit procedure

Before changing a large file:

```text
read relevant file region
↓
identify exact logical insertion/replacement points
↓
identify unique stable anchors
↓
plan several small edits
```

Do not start by generating the complete final file as one giant payload.

### Existing file

For an existing file:

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
    assume previous edit state without re-reading after a failed operation
```

Examples of one logical edit unit:

```text
one import group
one helper function
one class
one protocol method
one test class
one parametrized test matrix
one documentation subsection
one public export block
one status-record subsection
```

### New large file

For a new large file, create it incrementally.

Preferred sequence:

```text
operation 1:
    module docstring
    imports
    minimal helper/skeleton

operation 2:
    first logical implementation/test section

operation 3:
    second logical section

operation N:
    remaining independent sections
```

Do not attempt to create a several-hundred-line test/source file in one
`write` call when smaller logical sections can be created safely.

## 4. Patch-size reduction rule

If an IDE create/edit/patch operation fails because of payload size, parsing,
timeout, or transport:

```text
DO NOT change tools.
```

Instead:

```text
1. re-read the target region;
2. inspect git diff for already-applied content;
3. preserve correct partial work;
4. retry the same logical change with a smaller patch;
5. if it still fails, split that patch again;
6. repeat until each operation is reliably accepted.
```

A useful default is:

```text
one logical section per edit
```

If one logical section is still too large, divide it by structure rather than
by arbitrary character position.

For example:

```text
large test class
→ helpers
→ parametrized normal cases
→ ambiguity cases
→ validation cases
→ error-propagation cases
```

Never split Python code in the middle of a statement merely to satisfy the
tool.

## 5. Anchor requirements

Incremental edits must use stable, local, unique context.

Before applying a targeted edit, identify surrounding content such as:

```text
function/class declaration
section heading
existing test name
__all__ block
specific adjacent lines
```

Do not use an ambiguous one-line anchor that occurs many times in the file.

If the edit tool reports that an anchor was not found or was ambiguous:

```text
re-read the current file region
→ choose a more specific anchor
→ retry
```

Do not switch to shell mutation.

## 6. Never blindly append code

Blind append-to-EOF is prohibited for Python source and test files when the
content logically belongs inside an existing section/class/module structure.

This includes shell-based:

```text
open(path, "a").write(...)
Add-Content
>>
```

and equivalent IDE edits that simply dump unrelated code at EOF without
checking structure.

Before inserting content, determine where that content belongs.

## 7. Test-file construction policy

For large pytest changes, build the file in this order where applicable:

```text
shared fixtures/helpers
↓
small reusable fake/stub implementations
↓
parametrized normal cases
↓
special ambiguity/boundary cases
↓
validation/error cases
↓
integration/protocol regressions
```

Prefer:

```text
pytest.mark.parametrize
helpers
fixtures
small factories
```

when they reduce mechanical duplication.

Do not reduce acceptance coverage merely to make the file smaller.

Do not create hundreds of repeated test bodies when the same behavior can be
expressed clearly as a parametrized matrix.

## 8. Verification after incremental edits

After every substantial logical section, re-read the changed region.

After every few edit operations, inspect:

```text
git diff -- <affected-file>
```

Before moving to another file, verify that the current file has no:

```text
duplicate imports
duplicate classes/functions/tests
content inserted at the wrong location
truncated blocks
missing closing syntax
accidental repeated sections
partial failed-edit fragments
unrelated edits
```

For Python files, run the narrowest useful validation as soon as a coherent
unit exists.

Examples:

```text
uv run ruff check <file>
uv run ruff format --check <file>
uv run pytest <relevant-test-file>
```

Do not wait until the very end to discover that several incremental edits
corrupted file structure.

## 9. Recovery from partial success

If an edit operation partially succeeded:

```text
STOP assuming the original file contents.
```

Mandatory sequence:

```text
read current file
git diff -- <file>
identify what actually landed
preserve correct content
remove only broken/duplicated fragments
continue from current state with a smaller edit
```

Never repair a partial file by overwriting it wholesale unless a full-file
replacement is genuinely the smallest safe operation and the built-in file
tool can perform it reliably.

## 10. Shell-fallback exception

If built-in repository file tools are genuinely unavailable or objectively do
not support the required operation independent of payload size:

```text
STOP
→ explain the exact limitation to the user
→ request explicit approval for shell-based mutation
```

Without that approval, do not execute repository-writing shell commands.

A file-tool payload being too large is explicitly NOT such an exception.

## 11. Final mandatory check

Before claiming implementation complete:

```text
git status
git diff --check
git diff
```

Review the complete task diff for:

```text
truncation
duplicate code
accidental append artifacts
generated temporary files
unrelated changes
repository files written through prohibited shell fallback
```

If prohibited shell-based repository mutation occurred without explicit user
approval, report the violation and correct/review the affected file before
continuing.
