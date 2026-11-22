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

To check **every** overriding `execute` a suite runs, with no test of its own
per Transform, put one line in `conftest.py` (nw#281):

```default
from nw.testing.transforms import make_truthful_writes_fixture

truthful_writes = make_truthful_writes_fixture()
```

It wraps the `execute` of each class that owns a registered Transform’s
`execute` and fails the test at teardown with every misreport, so a caller’s
broad `except` cannot swallow the lie and a Transform added later is covered.

### Functions

| [`make_truthful_writes_fixture`](#nw.testing.transforms.make_truthful_writes_fixture)(\*[, ...])   | A pytest fixture checking every registered Transform's `execute` (nw#281).                                                                            |
|--------------------------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`recording_writes`](#nw.testing.transforms.recording_writes)(project)                 | Snapshot `project` now and, on exit, what the block wrote; [`WriteRecord.check()`](#nw.testing.transforms.WriteRecord.check) a result made inside. |

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

`require_traces="resolvable"` (nw#281) asks for that trace only when
every annotation parent of the row is in the graph: a unit scenario
that never adds the parents cannot be traced, so unconditionally
requiring it flags no production bug, while turning it off no longer
catches a raw `store.add`.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

#### written_in_call()

Ids written inside the block: new, changed (body, stamp or tier), or
re-written unchanged (a fresh verifying trace names them). Fixed when the
block exits; computed live while still inside it.

* **Return type:**
  [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)[[`UUID`](https://docs.python.org/3/library/uuid.html#uuid.UUID)]

### nw.testing.transforms.make_truthful_writes_fixture(\*, owner_filter=<function <lambda>>, require_traces='resolvable', autouse=True)

A pytest fixture checking every registered Transform’s `execute` (nw#281).

Like `falaw.testing.make_fake_assets_fixture`: call it in `conftest.py`
and bind the result to a name. While a test runs, the `execute` of each
class that owns a registered Transform’s `execute` is wrapped in
[`recording_writes()`](#nw.testing.transforms.recording_writes); at teardown every misreport is raised together as
one `AssertionError`. A nested `execute` (a `super().execute` call)
is checked once, at the outermost call. Only results that carry
`written` / `reused_ids` are checked.

`owner_filter(cls) -> bool` narrows which classes are wrapped (e.g. only
the host’s own package); `require_traces` is passed to
[`WriteRecord.check()`](#nw.testing.transforms.WriteRecord.check), default `"resolvable"`.

### nw.testing.transforms.recording_writes(project)

Snapshot `project` now and, on exit, what the block wrote;
[`WriteRecord.check()`](#nw.testing.transforms.WriteRecord.check) a result made inside.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/typing.html#typing.Iterator)[[`WriteRecord`](#nw.testing.transforms.WriteRecord)]
