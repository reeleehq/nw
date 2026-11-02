"""Freshness with **early cutoff** — what is *actually* out of date.

``descendants_of`` answers a reachability question: "what is downstream of
this?". :func:`stale_after` answers a freshness question: "what did this
change actually invalidate?". Those are different questions, and until this
module existed nw answered the second with the first — a one-line alias, so
editing one beat in a 200-shot project reported every descendant stale
whether or not anything about it had changed.

In *Build Systems à la Carte* terms that is the **Make** cell: a dirty-bit
rebuilder, "early cutoff: no". This module upgrades it to a **verifying
trace** rebuilder (Ninja, Shake, rustc/Salsa) using Salsa's *backdating*
idea: compare the value you have against the value the consumer recorded,
and stop when they agree. One 32-byte digest comparison replaces loading a
40 MB video, which is what makes cutoff free rather than pointless.

The rule, stated exactly
------------------------
The walk has two frontiers over the same rule: :func:`stale_verdicts` /
:func:`stale_after` classify everything reachable from a ``changed_id``;
:func:`stale_verdicts_all` / :func:`all_stale` classify every annotation
with at least one provenance parent — the whole-project snapshot a
freshness indicator wants (parentless annotations are never stale, or an
imported screenplay would read stale forever). An annotation ``X`` on the
frontier is **stale** when any of these holds, and **fresh** only when none
does:

- ``X`` itself carries an **unknown** ``generated_at_time`` — lacing's tick-0
  ``UNKNOWN_GENERATED_AT`` sentinel (rows written through the REST path
  before lacing#35 still carry it; lacing#44). A row that cannot be placed
  in time is unverifiable, and it is never read as "the oldest thing in the
  project". Regenerating ``X`` writes a fresh stamp, so this clears itself,
- no verifying trace was recorded for ``X`` (:mod:`nw.bodies.verifying_trace`),
- the trace was written under a different digest scheme,
- the trace's upstream set is not exactly ``X.provenance.was_derived_from``,
- a recorded upstream annotation no longer exists,
- a recorded upstream is **itself stale** — its value is about to change,
- a recorded upstream's *current* value digest differs from the recorded one.

**A tick-0 *parent* is not a verdict.** Only ``X``'s own stamp is checked.
Freshness has been digest-verified since nw#39: whether ``X``'s inputs
changed is answered by comparing the parents' *current* value digests to
the ones ``X`` recorded, and a parent's unknown timestamp says nothing about
that. Staling ``X`` for a tick-0 parent would also never converge — a
legacy authored root is never regenerated, so no recompute could clear it,
only the timestamp backfill (lacing#46) — and a ``regen_all_stale`` loop
built on this walk would spend forever on every project with a legacy REST
root. The one place a timestamp *does* decide something is the trace
backfill's bless walk (:func:`nw.graph.backfill_traces`), which now refuses
any row it cannot place against its parents.

Two consequences worth stating, because both are easy to get backwards:

**The comparison lives on the edge, not on the node.** It is tempting to
classify ``X`` as fresh and then prune the walk there. That is wrong: ``X``
having up-to-date *inputs* says nothing about whether ``X``'s own *value*
still equals what its children recorded. Rewriting ``X`` in place makes
``X`` fresh and its children stale at the same instant. So every reachable
node is classified against **its own** recorded digests; the walk prunes
nothing.

**Unverifiable means stale.** Every branch above defaults to stale.
Over-reporting wastes a recompute — which the content-addressed ``falaw``
cache makes close to free. Under-reporting serves a stale artifact as if it
were current, so every ambiguous case resolves the other way. For the
*scoped* walk this also means no data migration: an annotation written
before traces existed reads as ``no-trace`` and behaves exactly as it did
under pure reachability. The *snapshot* walk has no such equivalence — on a
pre-trace project it reports every derived annotation stale until each is
rewritten through the trace-writing path; see :func:`stale_verdicts_all`.

What this does **not** catch
-----------------------------
Stated so nobody reads more into the number than is there:

- **A changed Transform.** The trace records upstream *values*, not the
  producing code. Bumping a Transform's implementation or prompt does not
  move any digest. ``stale_after`` answers "what did this *annotation* change
  invalidate", not "what did this *code* change invalidate".
- **A hand-edited output.** Editing ``X``'s body directly leaves its trace
  matching its parents, so ``X`` reads fresh. That is the intended reading —
  a deliberate override is not stale relative to its inputs — but it does
  mean "fresh" is not "would regenerate identically".
- **The plan → execute window.** The trace is written when the output is
  *persisted*, so an upstream mutated between planning and writing is
  recorded at its newer value. That needs a concurrent edit during a render.
- **An artifact's bytes behind its id.** Artifact parents (64-hex asset
  ids in ``was_derived_from``, representable since thorwhalen/lacing#14 and
  written by :func:`~nw.transforms._provenance.derive_provenance` for
  inputs whose body schema declares its asset fields — nw#55,
  :mod:`nw.transforms.asset_refs`) are recorded in the trace's
  ``upstream_assets`` and never re-checked: an asset id *is* the SHA-256 of
  its bytes, so it cannot change, only be replaced — and for a *declared*
  ref, replacing it changes the body of the annotation that names it, which
  that annotation's own digest catches. A ref passed through
  ``derive_provenance(asset_refs=...)`` has no naming annotation, so it is
  trusted as-is: whether that artifact still exists, or has been superseded,
  is not checked. An artifact parent counts toward "the trace's upstream set
  is exactly ``was_derived_from``" like any other parent.

Reuse: the fresh equivalent of a new output
--------------------------------------------
:func:`fresh_equivalents` asks the walk a write-side question: *is there
already a node this new annotation would only duplicate?* (nw#203). Same
tier, ``body_schema_uri`` and reference, the same **annotation** parents, an
equal value (:func:`body_value`), and **verified fresh** — equality of
parents by id is not enough, because a parent rewritten in place keeps its
id (braidio#51). :meth:`nw.transforms.BaseTransform.execute` uses it, for a
Transform that declares ``reuse_fresh_outputs``, so that re-running it on
unchanged inputs (a falaw cache hit) returns the node it already wrote
instead of adding a second one. Inside a :func:`freshness_pass` (which
:func:`~nw.transforms.fanout.fan_out_execute` opens around its units), one
walk serves every lookup until something is written (nw#209).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from uuid import UUID

from lacing import Annotation
from lacing.model import partition_provenance_refs
from lacing.digest import (
    VALUE_DIGEST_SCHEMES,
    annotation_value_digest,
)

from .bodies.verifying_trace import (
    digest_vouches,
    recorded_exclusions,
    VERIFYING_TRACE_BODY_SCHEMA_URI,
    VerifyingTraceBodyV1,
)
from . import _freshness_pass
from .graph import annotations_at_tier, iter_all_annotations
from .storage import ProjectLike


# --- verdict reasons ---------------------------------------------------------
# Stable strings: they surface in reelee's freshness UI and in test assertions.

REASON_FRESH = "verified-fresh"
REASON_GENERATED_AT_UNKNOWN = "generated-at-unknown"
REASON_NO_TRACE = "no-trace"
REASON_SCHEME_CHANGED = "digest-scheme-changed"  # now: a scheme lacing does not know
REASON_TRACE_PARENTS_DIFFER = "trace-parents-differ"
REASON_TRACE_UNREADABLE = "trace-unreadable"
REASON_UPSTREAM_MISSING = "upstream-missing"
REASON_UPSTREAM_STALE = "upstream-stale"
REASON_UPSTREAM_CHANGED = "upstream-changed"
REASON_PROVENANCE_CYCLE = "provenance-cycle"


STALE_REASONS: tuple[str, ...] = (
    REASON_GENERATED_AT_UNKNOWN,
    REASON_NO_TRACE,
    REASON_SCHEME_CHANGED,
    REASON_TRACE_PARENTS_DIFFER,
    REASON_TRACE_UNREADABLE,
    REASON_UPSTREAM_MISSING,
    REASON_UPSTREAM_STALE,
    REASON_UPSTREAM_CHANGED,
    REASON_PROVENANCE_CYCLE,
)
"""Every reason that resolves to *stale*. :data:`REASON_FRESH` is the only
verdict that does not, which is the invariant that keeps "unverifiable means
stale" true by construction rather than by review."""


def is_verifiable_digest_scheme(scheme: str) -> bool:
    """Whether a trace recorded under ``scheme`` can still be verified.

    A trace is checked under the scheme it was *recorded* under (lacing keeps
    every released scheme computable), so a lacing upgrade does not turn old
    traces stale. Only a scheme lacing does not know is unverifiable. Note
    that a scheme whose digest depends on registered body schemas (v2) needs
    the verifier to register the same ``Derived`` markers as the producer, or
    the producer none (see ``vouches`` in the verdict walk, nw#179).
    """
    return scheme in VALUE_DIGEST_SCHEMES


@dataclass(frozen=True, slots=True)
class FreshnessVerdict:
    """Why one reachable annotation was judged stale (or not).

    Emitted by :func:`stale_verdicts`. ``reason`` is one of the
    ``REASON_*`` constants; ``upstream_id`` names the parent that decided it
    when a single parent did, so "why is this stale?" has an answer that does
    not require re-deriving the walk by hand.
    """

    annotation: Annotation
    is_stale: bool
    reason: str
    upstream_id: Optional[UUID] = None


def stale_verdicts(
    project_root: "ProjectLike", changed_id: UUID
) -> list[FreshnessVerdict]:
    """Classify every annotation downstream of ``changed_id``.

    The explained form of :func:`stale_after`: one verdict per reachable
    annotation, stale or not, in a deterministic order (generation time, then
    id). ``changed_id`` itself is never included — it is the source of the
    change, not a derivative of it.

    Use this when the *number* is being questioned. ``stale_after`` is the
    same walk with the fresh verdicts dropped;
    :func:`stale_verdicts_all` is the same classification with no
    ``changed_id`` — the whole-project snapshot.
    """
    annotations = list(iter_all_annotations(project_root))
    children = _children_index(annotations)
    reachable = _reachable_from(changed_id, children)
    return _verdicts_for(annotations, scope=reachable, recursion_scope=reachable)


def stale_verdicts_all(project_root: "ProjectLike") -> list[FreshnessVerdict]:
    """Classify every derived annotation in the project — the snapshot form.

    The question a freshness *indicator* asks: "what is stale in this
    project right now?", with no ``changed_id`` to anchor on. Same
    verifying-trace classification as :func:`stale_verdicts`, over a wider
    frontier: every annotation with at least one provenance parent.

    Two boundaries that are the point of this living here rather than each
    consumer approximating it (nw#39):

    - **Parentless annotations are never stale** and stay out of the walk —
      an imported screenplay must not read as stale forever. (nw-written
      verifying traces are parentless, so they stay out too.)
    - **Upstream-stale recursion runs over the whole derived set.** The
      scoped walk only recurses into parents inside ``reachable`` (outside
      it a parent is by construction unaffected by the change); with no
      change there is no such boundary. The cycle guard covers termination.

    **Legacy projects read all-stale, by design.** A derived annotation
    written before verifying traces existed classifies ``no-trace`` →
    stale, and unlike the scoped walk (which only surfaces it downstream
    of an actual change) the snapshot reports it *always*, until it is
    rewritten through the trace-writing path. A consumer replacing its own
    weaker snapshot with this one is making a behavior change on pre-trace
    projects, not installing a pure wrapper.
    """
    annotations = list(iter_all_annotations(project_root))
    derived = {a.id for a in annotations if a.provenance.was_derived_from}
    return _verdicts_for(annotations, scope=derived, recursion_scope=derived)


def all_stale(project_root: "ProjectLike") -> list[Annotation]:
    """Every annotation that is currently stale, regardless of cause.

    :func:`stale_verdicts_all` with the fresh verdicts dropped — the
    snapshot counterpart of :func:`stale_after`, and the primitive a
    freshness indicator or a "regenerate everything stale" verb should sit
    on instead of re-deriving its own definition of the word.
    """
    return [v.annotation for v in stale_verdicts_all(project_root) if v.is_stale]


def _verdicts_for(
    annotations: list[Annotation],
    *,
    scope: set[UUID],
    recursion_scope: set[UUID],
) -> list[FreshnessVerdict]:
    """Classify every annotation in ``scope``, in deterministic order.

    ``recursion_scope`` bounds the ``REASON_UPSTREAM_STALE`` recursion: a
    parent inside it is itself classified before the digest comparison; a
    parent outside it is only digest-compared. The scoped walk passes the
    reachable set for both (outside it, a parent is unaffected by the
    change); the whole-graph walk passes the derived set for both (a
    parentless parent has no verdict to take — it is never stale).
    """
    by_id: dict[UUID, Annotation] = {a.id: a for a in annotations}
    traces = _traces_by_target(annotations)

    primary: dict[tuple[UUID, str], Optional[str]] = {}
    fallback: dict[tuple, bool] = {}

    def vouches(
        ann: Annotation, recorded: str, scheme: str, excluded: Optional[frozenset]
    ) -> bool:
        """Whether ``recorded`` (a digest a trace stored under ``scheme``,
        leaving out the ``excluded`` paths) still describes ``ann``'s value.

        Today's digest first, memoized per ``(ann, scheme)``: nearly every
        trace matches it (nw#182). Only on a miss,
        :func:`~nw.bodies.verifying_trace.digest_vouches` (memoized per
        recorded digest) recomputes under the recorded exclusions while they
        are a subset of today's markers (nw#180), and accepts what a producer
        that knew no markers would have recorded (nw#179). None of these is a
        wrong hit; a verifier registering *fewer* markers than the producer,
        or a marker removed since, is a spurious miss. ``False`` when the body
        cannot be digested."""
        key = (ann.id, scheme)
        if key not in primary:
            try:
                primary[key] = annotation_value_digest(ann, scheme=scheme)
            except Exception:
                # A body outside the JSON contract (lacing raises
                # NonStringBodyKeyError) cannot be compared. Catching is the
                # load-bearing part — a read-only freshness query must not
                # crash on one broken row; the caller reads it as "changed".
                primary[key] = None
        if primary[key] is None:
            return False
        if recorded == primary[key]:
            return True
        miss = (ann.id, scheme, recorded, excluded)
        if miss not in fallback:
            try:
                fallback[miss] = digest_vouches(
                    ann, recorded, scheme=scheme, excluded=excluded
                )
            except Exception:  # same contract as above
                fallback[miss] = False
        return fallback[miss]

    verdicts: dict[UUID, FreshnessVerdict] = {}
    resolving: set[UUID] = set()

    def resolve(node_id: UUID) -> FreshnessVerdict:
        # Re-entry is impossible here: the only recursive caller is the parent
        # loop in `_classify`, which checks `resolving` itself so it can name
        # the cycle on the edge that closes it. Top-level calls always start
        # with `resolving` empty.
        cached = verdicts.get(node_id)
        if cached is not None:
            return cached
        resolving.add(node_id)
        try:
            verdict = _classify(node_id)
        finally:
            resolving.discard(node_id)
        verdicts[node_id] = verdict
        return verdict

    def _classify(node_id: UUID) -> FreshnessVerdict:
        ann = by_id[node_id]
        parents = tuple(dict.fromkeys(ann.provenance.was_derived_from))
        if not ann.provenance.generated_at_is_known:
            # Checked before the trace: a trace can match its parents'
            # digests and the row still cannot be placed in time (lacing#44).
            # Own stamp only — regenerating the row clears it.
            return FreshnessVerdict(ann, True, REASON_GENERATED_AT_UNKNOWN)
        trace = traces.get(node_id)
        if trace is None:
            return FreshnessVerdict(ann, True, REASON_NO_TRACE)
        if not is_verifiable_digest_scheme(trace.digest_scheme):
            return FreshnessVerdict(ann, True, REASON_SCHEME_CHANGED)
        try:
            recorded = {
                UUID(entry.annotation_id): (
                    entry.value_digest,
                    recorded_exclusions(entry),
                )
                for entry in trace.upstream
            }
        except (ValueError, AttributeError, TypeError):
            return FreshnessVerdict(ann, True, REASON_TRACE_UNREADABLE)
        if set(recorded) | set(trace.upstream_assets) != set(parents):
            # The trace does not describe this annotation's current parents —
            # a parent added, removed or rewritten since. Nothing to compare.
            return FreshnessVerdict(ann, True, REASON_TRACE_PARENTS_DIFFER)
        for pid in parents:
            if not isinstance(pid, UUID):
                # An artifact parent (64-hex asset id, nw#55): its id IS its
                # content digest, so it cannot have changed under us — and a
                # replaced artifact changes the body of the annotation that
                # names it, which that annotation's own digest catches.
                continue
            parent = by_id.get(pid)
            if parent is None:
                return FreshnessVerdict(ann, True, REASON_UPSTREAM_MISSING, pid)
            # Deliberately no timestamp check on the parent: see the module
            # docstring, "A tick-0 parent is not a verdict".
            if pid in recursion_scope:
                if pid in resolving:
                    # `pid` is an ancestor still being classified, so this edge
                    # closes a provenance cycle — malformed data. Reported on
                    # the edge that closes it rather than swallowed as a
                    # generic "upstream is stale", which is what a re-entry
                    # guard one level up would have produced (and which no
                    # caller could ever observe).
                    return FreshnessVerdict(ann, True, REASON_PROVENANCE_CYCLE, pid)
                if resolve(pid).is_stale:
                    return FreshnessVerdict(ann, True, REASON_UPSTREAM_STALE, pid)
            # ``vouches`` is False for a body lacing refuses to digest, so the
            # undigestible case falls to "changed" by construction rather than
            # by a separate branch that no test could distinguish.
            digest, excluded = recorded[pid]
            if not vouches(parent, digest, trace.digest_scheme, excluded):
                return FreshnessVerdict(ann, True, REASON_UPSTREAM_CHANGED, pid)
        return FreshnessVerdict(ann, False, REASON_FRESH)

    ordered = sorted(
        (by_id[i] for i in scope if i in by_id),
        key=lambda a: (a.provenance.generated_at_time.to_seconds(), str(a.id)),
    )
    return [resolve(ann.id) for ann in ordered]


def stale_after(project_root: "ProjectLike", changed_id: UUID) -> list[Annotation]:
    """Return every annotation that ``changed_id`` actually invalidated.

    The freshness operation. ``changed_id``'s descendants are walked and each
    is checked against the upstream value digests it recorded when it was
    written (:mod:`nw.bodies.verifying_trace`). A descendant whose recorded
    inputs still match the current ones is **not** returned — that is the
    early cutoff, and it is why this is not ``descendants_of`` under another
    name. The full rule, and the four things it deliberately does not catch,
    are in this module's docstring.

    The returned list does NOT include ``changed_id`` itself (it is the source
    of the change, not a stale derivative).

    ``descendants_of`` is unchanged and still answers the reachability
    question — "what is downstream of this?" is legitimate and the two verbs
    are no longer synonyms. Use :func:`stale_verdicts` when you need the
    *reason* a given annotation is in (or out of) this set.
    """
    return [
        v.annotation for v in stale_verdicts(project_root, changed_id) if v.is_stale
    ]


# --- reuse: the fresh equivalent of a new output (nw#203) --------------------


def body_value(ann: Annotation) -> object:
    """``ann.body`` JSON-normalised — the value two annotations are compared by.

    A body built in memory is a python-mode dump (tuples, UUIDs) while one read
    back from a store is what JSON gave it (lists, strings); the wire value is
    the same and must compare equal. Keys are sorted, so key order is not a
    difference either.
    """
    return json.loads(json.dumps(ann.body, sort_keys=True, default=str))


def annotation_parent_ids(ann: Annotation) -> frozenset[UUID]:
    """The **annotation** ids in ``ann.provenance.was_derived_from``.

    ``was_derived_from`` also holds 64-hex artifact asset ids (lacing#31,
    written for declared input schemas since nw#55). Code that means "the
    annotations this node was derived from" reads this half only — which is
    what lets a node written before #55 (no asset refs) still match one
    written after it.
    """
    annotation_ids, _asset_ids = partition_provenance_refs(
        list(ann.provenance.was_derived_from or ())
    )
    return frozenset(annotation_ids)


def fresh_equivalents(
    project_root: "ProjectLike",
    annotations: Iterable[Annotation],
    *,
    value_of: Callable[[Annotation], object] = body_value,
) -> tuple[Optional[Annotation], ...]:
    """For each of ``annotations``, the existing node it would only duplicate.

    Returns one entry per input, in order: the stored annotation equivalent to
    it, or ``None`` when there is none (write it). An existing node ``E`` is
    equivalent to a new annotation ``A`` when **all** of these hold:

    - same ``tier``, same ``body_schema_uri`` and the same ``reference``
      (where it sits — JSON-compared). Stricter than braidio's original rule,
      deliberately: two outputs at different places are different nodes even
      when every other field agrees, and a missed reuse only costs a write;
    - the same producer, ``provenance.was_generated_by``
      (``transform:<name>@<impl_version>``): another Transform's node is not
      this one's output, and after an ``impl_version`` bump the old
      version's node must not keep coming back — freshness does not see a
      changed Transform (this module's docstring), so the key has to;
    - the same **annotation** parents (:func:`annotation_parent_ids`, as a
      set). Artifact parents (nw#55) are ignored: a node written before the
      declaration has none, and comparing them would refuse to reuse every
      such node. Freshness loses nothing by it — a declared asset id is read
      off a parent's body, so replacing the artifact changes that parent's
      value, which the walk below refuses;
    - ``value_of(E) == value_of(A)`` — by default the whole body,
      JSON-normalised (:func:`body_value`). Generic on purpose: after a falaw
      cache hit the completed body *is* the earlier node's body, while a
      genuinely new render carries a different artifact id and so is never
      equivalent. A caller comparing a *planned* value before execution
      (braidio's ``planned_value``, which drops output keys) passes its own;
    - ``E`` is **verified fresh** by this module's walk, with the same
      classification :func:`stale_verdicts_all` gives it. Ids are not enough:
      a parent rewritten in place keeps its id, so a node derived from its
      old value has "the same parents" and is exactly the node that must not
      be reused (braidio#51). Unverifiable means stale here too: a node whose
      verifying trace is gone is never reused. A parentless ``E`` is never
      stale (the snapshot's own rule), so it counts as fresh;
    - ``E.id != A.id``.

    When several stored nodes qualify, the most recently generated one wins.

    Only **stored** nodes are candidates. Two equivalent annotations in the
    same call are matched against the graph, not against each other, so a
    caller that writes the ``None`` entries writes both; a later call then
    returns the newest of the two for each, so the result can name one node
    twice.

    **No lock** spans this read and the caller's write: two executes racing
    on the same outputs both find nothing and both write — exactly what
    happened without reuse, and nothing worse.

    **Cost.** The cheap filter runs first: one indexed ``by_tier`` read per
    distinct tier, each stored node's key computed once. The freshness walk
    runs **at most once per call**, over the candidates that survived it, and
    **not at all** when none did — so a first run, or a run whose outputs are
    all new, pays nothing for this. Pass every annotation of one write batch
    in a single call to share the walk. Inside a :func:`freshness_pass`, the
    tier reads and the walk are shared **across calls** too, until the next
    write. Read-only: nothing is written.
    """
    annotations = tuple(annotations)
    if not annotations:
        return ()

    def _identity(ann: Annotation) -> tuple:
        reference = json.dumps(
            ann.reference.model_dump(mode="json"), sort_keys=True, default=str
        )
        return (
            ann.tier,
            ann.body_schema_uri,
            reference,
            ann.provenance.was_generated_by,
            annotation_parent_ids(ann),
            json.dumps(value_of(ann), sort_keys=True, default=str),
        )

    held = _freshness_pass.held(project_root)
    held_tiers = held.setdefault("tiers", {}) if held is not None else {}
    stored: dict[tuple, list[Annotation]] = {}
    for tier in dict.fromkeys(a.tier for a in annotations):
        if tier not in held_tiers:
            held_tiers[tier] = annotations_at_tier(project_root, tier)
        for e in held_tiers[tier]:
            stored.setdefault(_identity(e), []).append(e)

    candidates_per_input = [
        [e for e in stored.get(_identity(ann), ()) if e.id != ann.id]
        for ann in annotations
    ]
    candidate_ids = {e.id for cands in candidates_per_input for e in cands}
    if not candidate_ids:
        return tuple(None for _ in annotations)

    if held is None:
        fresh = _fresh_among(project_root, candidate_ids)
    else:
        # One walk of every derived node, held until a write drops it: later
        # lookups in the pass ask about other candidates, and a scoped walk
        # would have to run again for each.
        if "fresh" not in held:
            held["fresh"] = _fresh_among(project_root, None)
        fresh = held["fresh"]

    def _newest_fresh(cands: list[Annotation]) -> Optional[Annotation]:
        ordered = sorted(
            (e for e in cands if e.id in fresh),
            key=lambda e: e.provenance.generated_at_time.to_seconds(),
        )
        return ordered[-1] if ordered else None

    return tuple(_newest_fresh(cands) for cands in candidates_per_input)


def _fresh_among(project_root: "ProjectLike", ids: Optional[set[UUID]]) -> set[UUID]:
    """Which of ``ids`` (every annotation, when ``None``) the snapshot walk
    verifies fresh — one walk.

    Classifies only ``ids`` (and, through the upstream-stale recursion, their
    derived ancestors), with :func:`stale_verdicts_all`'s recursion scope, so
    each verdict is the one the whole-project snapshot would give. A
    parentless id is never stale and is returned as fresh.
    """
    annotations = list(iter_all_annotations(project_root))
    derived = {a.id for a in annotations if a.provenance.was_derived_from}
    present = {a.id for a in annotations}
    if ids is not None:
        present &= ids
    verdicts = _verdicts_for(
        annotations, scope=present & derived, recursion_scope=derived
    )
    fresh = {v.annotation.id for v in verdicts if not v.is_stale}
    return fresh | (present - derived)


@contextmanager
def freshness_pass() -> Iterator[None]:
    """Share one freshness walk across many :func:`fresh_equivalents` lookups.

    While the pass is open, each project's tier reads and its freshness walk
    are taken once, on the first lookup that needs them, and reused by every
    later lookup — until a write drops them. Opening a pass reads and walks
    nothing, so it costs nothing to a run that never looks anything up.
    :func:`~nw.transforms.fanout.fan_out_execute` opens one around its units,
    which is what turns a K-unit re-run with ``reuse_fresh_outputs`` from K
    walks into one (nw#209). Nested passes share the outermost one.

    **Why a held walk stays valid** (braidio#171's rule): a node's freshness
    is a function of its own parents, so *adding* a node changes no other
    node's verdict. What can change one is a write to an existing node, a
    deletion, or a trace written later. So the held state is dropped by
    nw's write paths themselves, not by callers reporting their outputs — no
    caller can forget to:

    - every write-open of :class:`~nw.graph.ProjectGraph` (``add_annotation``
      and every entity upsert, ``remove_annotation``, ``backfill_traces``,
      a genre spec's entity sync). Unproduced-output records (nw#44) do not:
      they are parentless sidecars no node derives from, at a tier no lookup
      reads;
    - :func:`~nw.graph.remove_annotations_with_traces` (also a storyboard
      re-save);
    - :func:`nw.rewrite_values`.

    :func:`~nw.graph.collect_orphan_traces` does not: an orphan trace is
    never consulted, so removing one changes no answer.

    Not seen: a write that bypasses nw's writers (a raw ``store.add`` /
    ``store.remove`` on an opened store) or another process. Either can make
    a held answer stale for the rest of the pass — the window that, without
    a pass, is the one between a lookup and its write. A Transform that
    writes behind nw's back should not declare ``reuse_fresh_outputs``.

    State is per context (a :mod:`contextvars` variable) and keyed by the
    **resolved project root**: two projects in one pass never share it, two
    storages over one root do, and a thread that did not inherit the context
    sees no pass. Invalidation is not per context: a write in *any* thread
    moves a process-wide write epoch, and a held walk older than the epoch
    is discarded on its next use — so a request thread editing a shot while
    a fan-out runs on a worker drops that fan-out's walk too. It over-drops
    (a write to one project drops every project's held walk), which is safe.

    Held answers are **shared objects**: the annotations a lookup returns
    inside a pass may be the same instances later lookups return. Do not
    mutate them.
    """
    with _freshness_pass.open_pass():
        yield


# --- internals ---------------------------------------------------------------


def _traces_by_target(
    annotations: list[Annotation],
) -> dict[UUID, VerifyingTraceBodyV1]:
    """Index verifying traces by the annotation each describes.

    When more than one trace names the same target (an annotation re-added
    under the same id), the most recently generated one wins — it describes
    the state that is actually on disk.
    """
    best: dict[UUID, tuple[float, VerifyingTraceBodyV1]] = {}
    for ann in annotations:
        if ann.body_schema_uri != VERIFYING_TRACE_BODY_SCHEMA_URI:
            continue
        try:
            body = VerifyingTraceBodyV1.model_validate(ann.body)
            target = UUID(body.for_annotation_id)
        except Exception:
            continue
        at = ann.provenance.generated_at_time.to_seconds()
        current = best.get(target)
        if current is None or at >= current[0]:
            best[target] = (at, body)
    return {target: body for target, (_at, body) in best.items()}


def _children_index(annotations: list[Annotation]) -> dict[UUID, list[UUID]]:
    """``parent_id -> [child_id, ...]`` over ``provenance.was_derived_from``."""
    children: dict[UUID, list[UUID]] = {}
    for ann in annotations:
        for parent in ann.provenance.was_derived_from:
            children.setdefault(parent, []).append(ann.id)
    return children


def _reachable_from(ancestor_id: UUID, children: dict[UUID, list[UUID]]) -> set[UUID]:
    """Transitive closure of ``children`` from ``ancestor_id``, excluding it."""
    seen: set[UUID] = set()
    frontier = list(children.get(ancestor_id, ()))
    while frontier:
        cur = frontier.pop()
        if cur in seen:
            continue
        seen.add(cur)
        frontier.extend(children.get(cur, ()))
    return seen
