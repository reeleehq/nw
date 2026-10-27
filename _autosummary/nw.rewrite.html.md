# nw.rewrite

nw.rewrite — change stored annotation bodies without making dependents stale.

A vocabulary rename or slug change rewrites values already stored in a project’s
annotations. Done by hand that needs four things every caller would otherwise
reimplement (nw#132; the first user was reelee’s style-id rename):

1. \*\*One atomic `store.update` per row\*\* — no remove-then-add gap where a reader
   finds the annotation missing.
2. \*\*Under 

   ```
   ``
   ```

   Project.lock\`\`\*\*, the marker re-checked inside, so concurrent opens
   rewrite once.
3. **Verifying traces re-stamped.** Freshness compares value digests; a bare
   rewrite makes everything downstream read `upstream-changed`. Traces that
   recorded a rewritten annotation’s *old* digest get the *new* one. Only a
   digest matching the old body is touched, so a trace that was already stale
   stays stale.
4. **A success-only marker**, so a failed pass is retried on the next open and
   never recorded as done.

[`rewrite_values()`](#nw.rewrite.rewrite_values) is the primitive: `fn(body) -> body`, applied to every
annotation body in every scope of the project. It works through the project’s
[`ProjectStorage`](nw.storage.html.md#nw.storage.ProjectStorage) (a path, a storage, or an [`nw.Project`](nw.html.md#nw.Project)),
so a mapping-backed genre project is rewritten like a folder one. The marker lives
in the storage’s `docs` under [`MARKER_PREFIX`](#nw.rewrite.MARKER_PREFIX).

Two passes, traces first: a crash between them leaves the old bodies in place, so
a retry still finds them (the traces already hold the new digests and are skipped)
and the body pass then makes dependents fresh again. Bodies are rewritten from the
row as just read, so a write that landed since the plan was made is kept.

`fn` must be pure and idempotent (it runs again on retry), and must return a new
body or an equal one; returning an unchanged body leaves the row untouched. It may
change *values* but not identity: annotation ids, provenance and timestamps are
kept, because a rename is not a change of look.

### Module Attributes

| [`MARKER_PREFIX`](#nw.rewrite.MARKER_PREFIX)   | Key prefix, in `storage.docs`, of the success markers (`<prefix><name>.json`).              |
|------------------------------------------------------------------|---------------------------------------------------------------------------------------------|
| [`LOCK_NAME`](#nw.rewrite.LOCK_NAME)       | The one `project_lock()` every rewrite takes.                                               |
| [`MARKER_PATTERN`](#nw.rewrite.MARKER_PATTERN)  | a slug, so it cannot escape [`MARKER_PREFIX`](#nw.rewrite.MARKER_PREFIX). |

### Functions

| [`is_rewritten`](#nw.rewrite.is_rewritten)(project, marker)                    | Whether the rewrite named `marker` has completed on this project.                                                                                                                 |
|---------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`is_value_row`](#nw.rewrite.is_value_row)(ann)                                | The default `where`: every annotation except nw's verifying traces.                                                                                                               |
| [`mark_rewritten`](#nw.rewrite.mark_rewritten)(project, marker)                  | Record `marker` as done without scanning: for a project created already in today's vocabulary, so opening it never pays for the scan.                                             |
| [`rewrite_values`](#nw.rewrite.rewrite_values)(project, fn, \*[, marker, where]) | Apply `fn(body) -> body` to every stored annotation body; return how many changed.                                                                                                |
| [`unmark_rewritten`](#nw.rewrite.unmark_rewritten)(project, marker)                | Forget that `marker` ran, so the next [`rewrite_values()`](#nw.rewrite.rewrite_values) with it scans again (a test simulating a project made before the rename). |

### nw.rewrite.LOCK_NAME *= 'rewrite-values'*

The one `project_lock()` every rewrite takes. Not per marker:
two different rewrites planning from the same original bodies would each
invalidate the other’s digests.

### nw.rewrite.MARKER_PATTERN *= re.compile('[A-Za-z0-9][A-Za-z0-9_-]\*')*

a slug, so it cannot escape [`MARKER_PREFIX`](#nw.rewrite.MARKER_PREFIX).

* **Type:**
  What a marker name may be

### nw.rewrite.MARKER_PREFIX *= '.nw/rewrites/'*

Key prefix, in `storage.docs`, of the success markers (`<prefix><name>.json`).

### nw.rewrite.is_rewritten(project, marker)

Whether the rewrite named `marker` has completed on this project.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### nw.rewrite.is_value_row(ann)

The default `where`: every annotation except nw’s verifying traces.

A trace’s body is nw’s bookkeeping (digests, `for_annotation_id`), not a
stored value; a generic `fn` walking it would corrupt it, and the re-stamp
is what keeps it right.

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### nw.rewrite.mark_rewritten(project, marker)

Record `marker` as done without scanning: for a project created already
in today’s vocabulary, so opening it never pays for the scan.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)

### nw.rewrite.rewrite_values(project, fn, \*, marker=None, where=<function is_value_row>)

Apply `fn(body) -> body` to every stored annotation body; return how many changed.

`marker` names a one-time rewrite: when its marker exists nothing runs
(`0`); otherwise the lock is taken, the marker re-checked, the rewrite run,
and the marker written only after the pass finished cleanly. `None` runs
every time, under a lock of its own name, with no marker (idempotent `fn`
makes that safe).

`where(annotation) -> bool` picks the rows `fn` sees (default: everything
but verifying traces; `fn` can branch on `body_schema_uri` / tier there
instead of guessing from field names). `fn` gets a private copy of the body,
so mutating it in place is safe; return the new body.

With `marker=None` there is no done-record, so a caller must retry a raised
failure itself: the trace pass lands first, and until the body pass finishes
dependents read stale. A writer that does not take this lock and lands a trace
mid-rewrite leaves that trace stale (conservative, never wrong-fresh).

`project` is a path, a [`ProjectStorage`](nw.storage.html.md#nw.storage.ProjectStorage) or an
[`nw.Project`](nw.html.md#nw.Project); `marker` a slug ([`MARKER_PATTERN`](#nw.rewrite.MARKER_PATTERN)).

* **Return type:**
  [`int`](https://docs.python.org/3/builtins/functions.html#int)

### nw.rewrite.unmark_rewritten(project, marker)

Forget that `marker` ran, so the next [`rewrite_values()`](#nw.rewrite.rewrite_values) with it scans
again (a test simulating a project made before the rename). Idempotent: an
absent marker is not an error and writes nothing. A present one is removed
under [`LOCK_NAME`](#nw.rewrite.LOCK_NAME), so a rewrite about to write it cannot undo the
removal; its value is never read, so a corrupt marker can be cleared too.

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)
