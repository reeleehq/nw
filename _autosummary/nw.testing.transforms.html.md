# nw.testing.transforms

Conformance check: a Transform’s result says truthfully what it wrote (nw#234).

`nw.transforms.TransformResult.reused_ids` is an **obligation** on an
overriding `execute`: report every returned node it did not write in this
call (nw#215). nw cannot check that at runtime (overrides legitimately mint
ids), but a Transform author’s test can:

```default
from nw.testing.transforms import recording_writes

with recording_writes(project) as writes:
    result = my_transform.execute(project, plan, skeleton)
writes.check(result)  # AssertionError naming every misreported row
```

A row counts as **written in the call** when its id is new, its content changed
(body, generation stamp or tier: an in-place entity upsert counts), or a
verifying trace naming it was recorded during the call (a derived node
re-written unchanged; nw’s `add_annotation` records one per write, under a
fresh id). What counts is fixed when the `with` block exits.
[`WriteRecord.check()`](#nw.testing.transforms.WriteRecord.check) asserts every `result.written` row was, and every
`result.reused_ids` row was not. Run it over a host’s registered Transforms,
the way nw pins every `execute` signature.

### Functions

| [`recording_writes`](#nw.testing.transforms.recording_writes)(project)   | Snapshot `project` now and, on exit, what the block wrote; [`WriteRecord.check()`](#nw.testing.transforms.WriteRecord.check) a result made inside.   |
|------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------|

### Classes

| [`WriteRecord`](#nw.testing.transforms.WriteRecord)(project, before[, \_written])   | What [`recording_writes()`](#nw.testing.transforms.recording_writes) saw: the project on entry and, once the block has exited, what was written inside it.   |
|----------------------------------------------------------------------------------------------|------------------------------------------------------------------------------------------------------------------------------------------------------------------|

### *class* nw.testing.transforms.WriteRecord(project, before, \_written=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

What [`recording_writes()`](#nw.testing.transforms.recording_writes) saw: the project on entry and, once the
block has exited, what was written inside it.

#### check(result, , require_traces=True)

Raise `AssertionError` unless `result.written` / `result.reused_ids`
tell the truth (a real raise, so `python -O` cannot skip it).

`require_traces` (default `True`) also flags a written **derived**
row (one with `was_derived_from` parents) that got no verifying trace
in the block: written by a raw `store.add`, or by `add_annotation`
with a parent it could not resolve or digest, it reads stale forever
(nw#271). Only rows the result reports are scanned; a derived row
written but not reported is out of this check’s reach.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### written_in_call()

Ids written inside the block: new, changed (body, stamp or tier), or
re-written unchanged (a fresh verifying trace names them). Fixed when the
block exits; computed live while still inside it.

* **Return type:**
  [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)[[`UUID`](https://docs.python.org/3/library/uuid.html#uuid.UUID)]

### nw.testing.transforms.recording_writes(project)

Snapshot `project` now and, on exit, what the block wrote;
[`WriteRecord.check()`](#nw.testing.transforms.WriteRecord.check) a result made inside.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`WriteRecord`](#nw.testing.transforms.WriteRecord)]
