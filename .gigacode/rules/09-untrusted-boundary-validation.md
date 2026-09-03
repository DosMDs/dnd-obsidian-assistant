---
apply: ALWAYS
mode: ALL
---

# Untrusted boundary validation invariants

## 1. External data is untrusted until validated

All data arriving at a public boundary — from model providers, serialized
files, network responses, user input, configuration files, or any other
external source — must be treated as untrusted until explicitly validated.

This applies even when the data originates from localhost or a local process.

## 2. Structural-field equivalence classes

When validating untrusted structured data, explicitly consider the
structurally distinct states that each field can occupy.

Where semantically applicable, review:

```text
field missing
None / null
expected empty container (e.g. [] for a list, {} for a dict)
wrong empty container type
empty string ""
integer 0
bool False
bool True
valid non-empty value
malformed non-empty value
```

### Truthiness is not structural validation

Do not use `if value:` when missing, empty, zero, false, null, malformed,
and valid values have different contract meanings.

A truthiness check collapses multiple semantically distinct states into one
boolean. Each equivalence class must be evaluated independently when the
contract distinguishes them.

### Presence, type, cardinality, semantic validity

These are separate validation dimensions. Each must be reasoned about
independently:

```text
presence:     does the field exist in the data structure?
type:         is the value the expected Python type?
cardinality:  is the length/size within acceptable bounds?
semantic:     does the value satisfy domain constraints?
```

### Presence-vs-value invariant

When field presence itself is meaningful:

```python
if "field" not in data:
    ...
```

is semantically different from:

```python
value = data.get("field")
if value:
    ...
```

The first checks whether the key exists. The second conflates absence,
None, empty, zero, and false into a single branch.

Choose the check that matches the contract semantics.

## 3. Numeric boundary invariants

### Python numeric traps

Python has several numeric behaviors that differ from expectations in many
other languages and must be explicitly considered at untrusted boundaries:

```text
bool is a subclass of int
    isinstance(True, int) is True
    True + 1 == 2

NaN is a valid float
    float("nan") produces a float

+Infinity / -Infinity are valid floats
    float("inf") and float("-inf") produce floats

Python integers have arbitrary precision
    they can be arbitrarily large

a mathematically finite Python int may not be representable as float
    int -> float conversion can overflow to Infinity

numeric conversion may raise OverflowError
```

### Bool-before-int rule

If `bool` is semantically invalid for a field but `int` is valid, reject
`bool` before generic `int` checks:

```python
if isinstance(value, bool):
    raise TypeError("bool is not valid here")

if not isinstance(value, int):
    raise TypeError("expected int")
```

Do not depend on developers remembering that `bool` is an `int` subclass.

### Non-finite numeric values

NaN, +Infinity, and -Infinity must be explicitly handled or rejected when
accepting `float` values from untrusted sources:

```python
import math

if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
    raise ValueError("non-finite float not allowed")
```

### Oversized integer conversion

When converting an externally supplied integer to `float`, the conversion
may overflow:

```python
# int -> float: may raise OverflowError or produce Infinity
try:
    result = float(large_int_value)
except OverflowError:
    # handle or reject
    ...
```

### Validate/coerce once

Validate or coerce at the boundary, then validate the converted
representation, then use the already-validated converted value.

Avoid:

```text
validate original
→ later independently convert again
```

when the conversion itself has failure semantics.

For example, an API returning `list[list[float]]` must reject an integer
that cannot actually become a finite Python float at the conversion point,
not assume the original integer was safe.

## 4. Public exception-containment rule

For adapters and public boundaries that handle external data, review the
incidental exceptions that may arise from:

```text
parsing
decoding
coercion
validation
mapping
indexing
attribute access
third-party library calls
```

The owning public boundary must intentionally decide whether each such
exception becomes:

```text
a project-level error (wrapped in a domain exception)
a validated result or state
an intentionally documented programming error (assertion)
```

Do not let incidental implementation exceptions leak past the public
boundary merely because the happy path type-checks.

Prefer narrow failure boundaries over broad `except Exception` around
entire functions.

## 5. Cross-reference

See also:

- `.gigacode/skills/model-gateway/SKILL.md` — provider-specific application
  of these rules.
- `.gigacode/skills/testing/SKILL.md` — equivalence-class test design.
- `.gigacode/skills/code-review/SKILL.md` — reviewer checklist for
  boundary validation.