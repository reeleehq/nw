# nw.freshness

Freshness with **early cutoff** — what is *actually* out of date.

`descendants_of` answers a reachability question: “what is downstream of
this?”. [`stale_after()`](#nw.freshness.stale_after) answers a freshness question: “what did this
change actually invalidate?”. Those are different questions, and until this
module existed nw answered the second with the first — a one-line alias, so
editing one beat in a 200-shot project reported every descendant stale
whether or not anything about it had changed.

In *Build Systems à la Carte* terms that is the **Make** cell: a dirty-bit
rebuilder, “early cutoff: no”. This module upgrades it to a \*\*verifying
trace\*\* rebuilder (Ninja, Shake, rustc/Salsa) using Salsa’s *backdating*
idea: compare the value you have against the value the consumer recorded,
and stop when they agree. One 32-byte digest comparison replaces loading a
40 MB video, which is what makes cutoff free rather than pointless.

## The rule, stated exactly

The walk has two frontiers over the same rule: [`stale_verdicts()`](#nw.freshness.stale_verdicts) /
[`stale_after()`](#nw.freshness.stale_after) classify everything reachable from a `changed_id`;
[`stale_verdicts_all()`](#nw.freshness.stale_verdicts_all) / [`all_stale()`](#nw.freshness.all_stale) classify every annotation
with at least one provenance parent — the whole-project snapshot a
freshness indicator wants (parentless annotations are never stale, or an
imported screenplay would read stale forever). An annotation `X` on the
frontier is **stale** when any of these holds, and **fresh** only when none
does:

- `X` itself carries an **unknown** `generated_at_time` — lacing’s tick-0
  `UNKNOWN_GENERATED_AT` sentinel (rows written through the REST path
  before lacing#35 still carry it; lacing#44). A row that cannot be placed
  in time is unverifiable, and it is never read as “the oldest thing in the
  project”. Regenerating `X` writes a fresh stamp, so this clears itself,
- no verifying trace was recorded for `X` ([`nw.bodies.verifying_trace`](nw.bodies.verifying_trace.html.md#module-nw.bodies.verifying_trace)),
- the trace was written under a different digest scheme,
- the trace’s upstream set is not exactly `X.provenance.was_derived_from`,
- a recorded upstream annotation no longer exists,
- a recorded upstream is **itself stale** — its value is about to change,
- a recorded upstream’s *current* value digest differs from the recorded one.

**A tick-0 \*parent\* is not a verdict.** Only `X`’s own stamp is checked.
Freshness has been digest-verified since nw#39: whether `X`’s inputs
changed is answered by comparing the parents’ *current* value digests to
the ones `X` recorded, and a parent’s unknown timestamp says nothing about
that. Staling `X` for a tick-0 parent would also never converge — a
legacy authored root is never regenerated, so no recompute could clear it,
only the timestamp backfill (lacing#46) — and a `regen_all_stale` loop
built on this walk would spend forever on every project with a legacy REST
root. The one place a timestamp *does* decide something is the trace
backfill’s bless walk ([`nw.graph.backfill_traces()`](nw.graph.html.md#nw.graph.backfill_traces)), which now refuses
any row it cannot place against its parents.

Two consequences worth stating, because both are easy to get backwards:

**The comparison lives on the edge, not on the node.** It is tempting to
classify `X` as fresh and then prune the walk there. That is wrong: `X`
having up-to-date *inputs* says nothing about whether `X`’s own *value*
still equals what its children recorded. Rewriting `X` in place makes
`X` fresh and its children stale at the same instant. So every reachable
node is classified against **its own** recorded digests; the walk prunes
nothing.

**Unverifiable means stale.** Every branch above defaults to stale.
Over-reporting wastes a recompute — which the content-addressed `falaw`
cache makes close to free. Under-reporting serves a stale artifact as if it
were current, so every ambiguous case resolves the other way. For the
*scoped* walk this also means no data migration: an annotation written
before traces existed reads as `no-trace` and behaves exactly as it did
under pure reachability. The *snapshot* walk has no such equivalence — on a
pre-trace project it reports every derived annotation stale until each is
rewritten through the trace-writing path; see [`stale_verdicts_all()`](#nw.freshness.stale_verdicts_all).

## What this does **not** catch

Stated so nobody reads more into the number than is there:

- **A changed Transform.** The trace records upstream *values*, not the
  producing code. Bumping a Transform’s implementation or prompt does not
  move any digest. `stale_after` answers “what did this *annotation* change
  invalidate”, not “what did this *code* change invalidate”.
- **A hand-edited output.** Editing `X`’s body directly leaves its trace
  matching its parents, so `X` reads fresh. That is the intended reading —
  a deliberate override is not stale relative to its inputs — but it does
  mean “fresh” is not “would regenerate identically”.
- **The plan → execute window.** The trace is written when the output is
  *persisted*, so an upstream mutated between planning and writing is
  recorded at its newer value. That needs a concurrent edit during a render.
- **An artifact’s bytes behind its id.** Artifact parents (64-hex asset
  ids in `was_derived_from`, representable since thorwhalen/lacing#14 and
  written by `derive_provenance()` for
  inputs whose body schema declares its asset fields — nw#55,
  `nw.transforms.asset_refs`) are recorded in the trace’s
  > `upstream_assets` and never re-checked: an asset id *is* the SHA-256 of
  > its bytes, so it cannot change, only be replaced — and for a *declared*
  > ref, replacing it changes the body of the annotation that names it, which
  > that annotation’s own digest catches. A ref passed through
  > `derive_provenance(asset_refs=...)` has no naming annotation, so it is
  > trusted as-is: whether that artifact still exists, or has been superseded,
  > is not checked. An artifact parent counts toward “the trace’s upstream set
  > is exactly `was_derived_from`” like any other parent.

## Reuse: the fresh equivalent of a new output

[`fresh_equivalents()`](#nw.freshness.fresh_equivalents) asks the walk a write-side question: \*is there
already a node this new annotation would only duplicate?\* (nw#203). Same
tier, `body_schema_uri` and reference, the same **annotation** parents, an
equal value ([`body_value()`](#nw.freshness.body_value)), and **verified fresh** — equality of
parents by id is not enough, because a parent rewritten in place keeps its
id (braidio#51). `nw.transforms.BaseTransform.execute()` uses it, for a
Transform that declares `reuse_fresh_outputs`, so that re-running it on
unchanged inputs (a falaw cache hit) returns the node it already wrote
instead of adding a second one. Inside a [`freshness_pass()`](#nw.freshness.freshness_pass) (which
`fan_out_execute()` opens around its units), one
walk serves every lookup until something is written (nw#209).

### Module Attributes

| [`STALE_REASONS`](#nw.freshness.STALE_REASONS)   | Every reason that resolves to *stale*.   |
|------------------------------------------------------------------|------------------------------------------|

### Functions

| [`all_stale`](#nw.freshness.all_stale)(project_root)                          | Every annotation that is currently stale, regardless of cause.                                                     |
|---------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------|
| [`annotation_parent_ids`](#nw.freshness.annotation_parent_ids)(ann)                       | The **annotation** ids in `ann.provenance.was_derived_from`.                                                       |
| [`body_value`](#nw.freshness.body_value)(ann)                                  | `ann.body` JSON-normalised — the value two annotations are compared by.                                            |
| [`fresh_equivalents`](#nw.freshness.fresh_equivalents)(project_root, annotations, \*) | For each of `annotations`, the existing node it would only duplicate.                                              |
| [`freshness_pass`](#nw.freshness.freshness_pass)()                                 | Share one freshness walk across many [`fresh_equivalents()`](#nw.freshness.fresh_equivalents) lookups. |
| [`is_verifiable_digest_scheme`](#nw.freshness.is_verifiable_digest_scheme)(scheme)              | Whether a trace recorded under `scheme` can still be verified.                                                     |
| [`stale_after`](#nw.freshness.stale_after)(project_root, changed_id)            | Return every annotation that `changed_id` actually invalidated.                                                    |
| [`stale_verdicts`](#nw.freshness.stale_verdicts)(project_root, changed_id)         | Classify every annotation downstream of `changed_id`.                                                              |
| [`stale_verdicts_all`](#nw.freshness.stale_verdicts_all)(project_root)                 | Classify every derived annotation in the project — the snapshot form.                                              |

### Classes

| [`FreshnessVerdict`](#nw.freshness.FreshnessVerdict)(annotation, is_stale, reason)   | Why one reachable annotation was judged stale (or not).   |
|---------------------------------------------------------------------------------------------------|-----------------------------------------------------------|

### *class* nw.freshness.FreshnessVerdict(annotation, is_stale, reason, upstream_id=None)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

Why one reachable annotation was judged stale (or not).

Emitted by [`stale_verdicts()`](#nw.freshness.stale_verdicts). `reason` is one of the
`REASON_*` constants; `upstream_id` names the parent that decided it
when a single parent did, so “why is this stale?” has an answer that does
not require re-deriving the walk by hand.

### nw.freshness.STALE_REASONS *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), ...]* *= ('generated-at-unknown', 'no-trace', 'digest-scheme-changed', 'trace-parents-differ', 'trace-unreadable', 'upstream-missing', 'upstream-stale', 'upstream-changed', 'provenance-cycle')*

Every reason that resolves to *stale*. `REASON_FRESH` is the only
verdict that does not, which is the invariant that keeps “unverifiable means
stale” true by construction rather than by review.

### nw.freshness.all_stale(project_root)

Every annotation that is currently stale, regardless of cause.

[`stale_verdicts_all()`](#nw.freshness.stale_verdicts_all) with the fresh verdicts dropped — the
snapshot counterpart of [`stale_after()`](#nw.freshness.stale_after), and the primitive a
freshness indicator or a “regenerate everything stale” verb should sit
on instead of re-deriving its own definition of the word.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[`Annotation`]

### nw.freshness.annotation_parent_ids(ann)

The **annotation** ids in `ann.provenance.was_derived_from`.

`was_derived_from` also holds 64-hex artifact asset ids (lacing#31,
written for declared input schemas since nw#55). Code that means “the
annotations this node was derived from” reads this half only — which is
what lets a node written before #55 (no asset refs) still match one
written after it.

* **Return type:**
  [`frozenset`](https://docs.python.org/3/builtins/stdtypes.html#frozenset)[[`UUID`](https://docs.python.org/3/library/uuid.html#uuid.UUID)]

### nw.freshness.body_value(ann)

`ann.body` JSON-normalised — the value two annotations are compared by.

A body built in memory is a python-mode dump (tuples, UUIDs) while one read
back from a store is what JSON gave it (lists, strings); the wire value is
the same and must compare equal. Keys are sorted, so key order is not a
difference either.

* **Return type:**
  [`object`](https://docs.python.org/3/builtins/functions.html#object)

### nw.freshness.fresh_equivalents(project_root, annotations, \*, value_of=<function body_value>)

For each of `annotations`, the existing node it would only duplicate.

Returns one entry per input, in order: the stored annotation equivalent to
it, or `None` when there is none (write it). An existing node `E` is
equivalent to a new annotation `A` when **all** of these hold:

- same `tier`, same `body_schema_uri` and the same `reference`
  (where it sits — JSON-compared). Stricter than braidio’s original rule,
  deliberately: two outputs at different places are different nodes even
  when every other field agrees, and a missed reuse only costs a write;
- the same producer, `provenance.was_generated_by`
  (`transform:<name>@<impl_version>`): another Transform’s node is not
  this one’s output, and after an `impl_version` bump the old
  version’s node must not keep coming back — freshness does not see a
  changed Transform (this module’s docstring), so the key has to;
- the same **annotation** parents ([`annotation_parent_ids()`](#nw.freshness.annotation_parent_ids), as a
  set). Artifact parents (nw#55) are ignored: a node written before the
  declaration has none, and comparing them would refuse to reuse every
  such node. Freshness loses nothing by it — a declared asset id is read
  off a parent’s body, so replacing the artifact changes that parent’s
  value, which the walk below refuses;
- `value_of(E) == value_of(A)` — by default the whole body,
  JSON-normalised ([`body_value()`](#nw.freshness.body_value)). Generic on purpose: after a falaw
  cache hit the completed body *is* the earlier node’s body, while a
  genuinely new render carries a different artifact id and so is never
  equivalent. A caller comparing a *planned* value before execution
  (braidio’s `planned_value`, which drops output keys) passes its own;
- `E` is **verified fresh** by this module’s walk, with the same
  classification [`stale_verdicts_all()`](#nw.freshness.stale_verdicts_all) gives it. Ids are not enough:
  a parent rewritten in place keeps its id, so a node derived from its
  old value has “the same parents” and is exactly the node that must not
  be reused (braidio#51). Unverifiable means stale here too: a node whose
  verifying trace is gone is never reused. A parentless `E` is never
  stale (the snapshot’s own rule), so it counts as fresh;
- `E.id != A.id`.

When several stored nodes qualify, the most recently generated one wins.

Only **stored** nodes are candidates. Two equivalent annotations in the
same call are matched against the graph, not against each other, so a
caller that writes the `None` entries writes both; a later call then
returns the newest of the two for each, so the result can name one node
twice.

**No lock** spans this read and the caller’s write: two executes racing
on the same outputs both find nothing and both write — exactly what
happened without reuse, and nothing worse.

**Cost.** The cheap filter runs first: one indexed `by_tier` read per
distinct tier, each stored node’s key computed once. The freshness walk
runs **at most once per call**, over the candidates that survived it, and
**not at all** when none did — so a first run, or a run whose outputs are
all new, pays nothing for this. Pass every annotation of one write batch
in a single call to share the walk. Inside a [`freshness_pass()`](#nw.freshness.freshness_pass), the
tier reads and the walk are shared **across calls** too, until the next
write. Read-only: nothing is written.

* **Return type:**
  [`tuple`](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[`Optional`](https://docs.python.org/3/library/typing.html#typing.Optional)[`Annotation`], [`...`](https://docs.python.org/3/builtins/constants.html#Ellipsis)]

### nw.freshness.freshness_pass()

Share one freshness walk across many [`fresh_equivalents()`](#nw.freshness.fresh_equivalents) lookups.

While the pass is open, each project’s tier reads and its freshness walk
are taken once, on the first lookup that needs them, and reused by every
later lookup — until a write drops them. Opening a pass reads and walks
nothing, so it costs nothing to a run that never looks anything up.
`fan_out_execute()` opens one around its units,
which is what turns a K-unit re-run with `reuse_fresh_outputs` from K
walks into one (nw#209). Nested passes share the outermost one.

**Why a held walk stays valid** (braidio#171’s rule): a node’s freshness
is a function of its own parents, so *adding* a node changes no other
node’s verdict. What can change one is a write to an existing node, a
deletion, or a trace written later. So the held state is dropped by
nw’s write paths themselves, not by callers reporting their outputs — no
caller can forget to:

- every write-open of [`ProjectGraph`](nw.graph.html.md#nw.graph.ProjectGraph) (`add_annotation`
  and every entity upsert, `remove_annotation`, `backfill_traces`,
  a genre spec’s entity sync). Unproduced-output records (nw#44) do not:
  they are parentless sidecars no node derives from, at a tier no lookup
  reads;
- [`remove_annotations_with_traces()`](nw.graph.html.md#nw.graph.remove_annotations_with_traces) (also a storyboard
  re-save);
- [`nw.rewrite_values()`](nw.html.md#nw.rewrite_values).

[`collect_orphan_traces()`](nw.graph.html.md#nw.graph.collect_orphan_traces) does not: an orphan trace is
never consulted, so removing one changes no answer.

Not seen: a write that bypasses nw’s writers (a raw `store.add` /
`store.remove` on an opened store) or another process. Either can make
a held answer stale for the rest of the pass — the window that, without
a pass, is the one between a lookup and its write. A Transform that
writes behind nw’s back should not declare `reuse_fresh_outputs`.

State is per context (a [`contextvars`](https://docs.python.org/3/library/contextvars.html#module-contextvars) variable) and keyed by the
**resolved project root**: two projects in one pass never share it, two
storages over one root do, and a thread that did not inherit the context
sees no pass. Invalidation is not per context: a write in *any* thread
moves a process-wide write epoch, and a held walk older than the epoch
is discarded on its next use — so a request thread editing a shot while
a fan-out runs on a worker drops that fan-out’s walk too. It over-drops
(a write to one project drops every project’s held walk), which is safe.

Held answers are **shared objects**: the annotations a lookup returns
inside a pass may be the same instances later lookups return. Do not
mutate them.

* **Return type:**
  [`Iterator`](https://docs.python.org/3/library/collections.abc.html#collections.abc.Iterator)[[`None`](https://docs.python.org/3/builtins/constants.html#None)]

### nw.freshness.is_verifiable_digest_scheme(scheme)

Whether a trace recorded under `scheme` can still be verified.

A trace is checked under the scheme it was *recorded* under (lacing keeps
every released scheme computable), so a lacing upgrade does not turn old
traces stale. Only a scheme lacing does not know is unverifiable. Note
that a scheme whose digest depends on registered body schemas (v2) needs
the verifier to register the same `Derived` markers as the producer, or
the producer none (see `vouches` in the verdict walk, nw#179).

* **Return type:**
  [`bool`](https://docs.python.org/3/builtins/functions.html#bool)

### nw.freshness.stale_after(project_root, changed_id)

Return every annotation that `changed_id` actually invalidated.

The freshness operation. `changed_id`’s descendants are walked and each
is checked against the upstream value digests it recorded when it was
written ([`nw.bodies.verifying_trace`](nw.bodies.verifying_trace.html.md#module-nw.bodies.verifying_trace)). A descendant whose recorded
inputs still match the current ones is **not** returned — that is the
early cutoff, and it is why this is not `descendants_of` under another
name. The full rule, and the four things it deliberately does not catch,
are in this module’s docstring.

The returned list does NOT include `changed_id` itself (it is the source
of the change, not a stale derivative).

`descendants_of` is unchanged and still answers the reachability
question — “what is downstream of this?” is legitimate and the two verbs
are no longer synonyms. Use [`stale_verdicts()`](#nw.freshness.stale_verdicts) when you need the
*reason* a given annotation is in (or out of) this set.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[`Annotation`]

### nw.freshness.stale_verdicts(project_root, changed_id)

Classify every annotation downstream of `changed_id`.

The explained form of [`stale_after()`](#nw.freshness.stale_after): one verdict per reachable
annotation, stale or not, in a deterministic order (generation time, then
id). `changed_id` itself is never included — it is the source of the
change, not a derivative of it.

Use this when the *number* is being questioned. `stale_after` is the
same walk with the fresh verdicts dropped;
[`stale_verdicts_all()`](#nw.freshness.stale_verdicts_all) is the same classification with no
`changed_id` — the whole-project snapshot.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`FreshnessVerdict`](#nw.freshness.FreshnessVerdict)]

### nw.freshness.stale_verdicts_all(project_root)

Classify every derived annotation in the project — the snapshot form.

The question a freshness *indicator* asks: “what is stale in this
project right now?”, with no `changed_id` to anchor on. Same
verifying-trace classification as [`stale_verdicts()`](#nw.freshness.stale_verdicts), over a wider
frontier: every annotation with at least one provenance parent.

Two boundaries that are the point of this living here rather than each
consumer approximating it (nw#39):

- **Parentless annotations are never stale** and stay out of the walk —
  an imported screenplay must not read as stale forever. (nw-written
  verifying traces are parentless, so they stay out too.)
- **Upstream-stale recursion runs over the whole derived set.** The
  scoped walk only recurses into parents inside `reachable` (outside
  it a parent is by construction unaffected by the change); with no
  change there is no such boundary. The cycle guard covers termination.

**Legacy projects read all-stale, by design.** A derived annotation
written before verifying traces existed classifies `no-trace` →
stale, and unlike the scoped walk (which only surfaces it downstream
of an actual change) the snapshot reports it *always*, until it is
rewritten through the trace-writing path. A consumer replacing its own
weaker snapshot with this one is making a behavior change on pre-trace
projects, not installing a pure wrapper.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`FreshnessVerdict`](#nw.freshness.FreshnessVerdict)]
