# Untrusted boundaries

Read this when a task validates external input, parses provider/model/framework
data, handles numeric boundaries, or crosses any public boundary. This is
project-wide and not framework-specific.

## 1. External data is untrusted until validated

All data arriving at a public boundary — from model providers, serialized files,
network responses, user input, configuration files or any other external source
— must be treated as untrusted until explicitly validated. This applies even
when the data originates from localhost or a local process.

## 2. Structural-field equivalence classes

When validating untrusted structured data, explicitly consider the structurally
distinct states each field can occupy. Where semantically applicable, review:

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

Do not use `if value:` when missing, empty, zero, false, null, malformed and
valid values have different contract meanings. A truthiness check collapses
semantically distinct states into one boolean; evaluate each equivalence class
independently when the contract distinguishes them.

### Presence, type, cardinality, semantic validity

These are separate dimensions and must be reasoned about independently:

```text
presence:     does the field exist in the data structure?
type:         is the value the expected Python type?
cardinality:  is the length/size within acceptable bounds?
semantic:     does the value satisfy domain constraints?
```

### Presence-vs-value invariant

When field presence itself is meaningful, `if "field" not in data:` is
semantically different from `value = data.get("field"); if value:`. The first
checks key existence; the second conflates absence, `None`, empty, zero and
false. Choose the check that matches contract semantics.

## 3. Numeric boundary invariants

### Python numeric traps

```text
bool is a subclass of int
    isinstance(True, int) is True; True + 1 == 2

NaN is a valid float
    float("nan") produces a float

+Infinity / -Infinity are valid floats
    float("inf") and float("-inf") produce floats

Python integers have arbitrary precision (can be arbitrarily large)

a mathematically finite Python int may not be representable as float
    built-in int -> float conversion may raise OverflowError
```

### Bool-before-int rule

If `bool` is semantically invalid for a field but `int` is valid, reject `bool`
before generic `int` checks:

```python
if isinstance(value, bool):
    raise TypeError("bool is not valid here")

if not isinstance(value, int):
    raise TypeError("expected int")
```

Do not depend on developers remembering that `bool` is an `int` subclass.

### Non-finite numeric values

NaN, +Infinity and -Infinity must be explicitly handled or rejected when
accepting `float` from untrusted sources:

```python
import math

if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
    raise ValueError("non-finite float not allowed")
```

### Oversized integer conversion

When converting an externally supplied integer to `float`, the conversion may
overflow:

```python
try:
    result = float(large_int_value)
except OverflowError:
    # handle or reject
    ...
```

### Validate/coerce once

Validate or coerce at the boundary, validate the converted representation, then
use the already-validated converted value. Avoid "validate original, then
independently convert again" when the conversion itself has failure semantics.
For example, an API returning `list[list[float]]` must reject an integer that
cannot actually become a finite Python float at the conversion point, not assume
the original integer was safe.

## 4. Public exception containment

For adapters and public boundaries handling external data, review incidental
exceptions from parsing, decoding, coercion, validation, mapping, indexing,
attribute access and third-party library calls. The owning public boundary must
intentionally decide whether each becomes a project-level error (wrapped in a
domain exception), a validated result/state, or a documented programming error
(assertion). Do not let incidental implementation exceptions leak past the
public boundary merely because the happy path type-checks. Prefer narrow failure
boundaries over broad `except Exception` around entire functions.

## 5. Paths and filesystem

Normalize and validate paths and reject traversal outside the allowed root.
Filesystem-boundary rules (atomic writes, revisions, audit, Vault write safety)
are in [project-invariants.md](project-invariants.md).

## 6. Cross-reference

Provider-specific application of these rules and equivalence-class test design
are covered by the relevant model-gateway/testing skills (added in OC-03).
