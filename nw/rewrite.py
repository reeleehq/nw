"""nw.rewrite — change stored annotation bodies without making dependents stale.

A vocabulary rename or slug change rewrites values already stored in a project's
annotations. Done by hand that needs four things every caller would otherwise
reimplement (nw#132; the first user was reelee's style-id rename):

1. **One atomic ``store.update`` per row** — no remove-then-add gap where a reader
   finds the annotation missing.
2. **Under ``Project.lock``**, the marker re-checked inside, so concurrent opens
   rewrite once.
3. **Verifying traces re-stamped.** Freshness compares value digests; a bare
   rewrite makes everything downstream read ``upstream-changed``. Traces that
   recorded a rewritten annotation's *old* digest get the *new* one. Only a
   digest matching the old body is touched, so a trace that was already stale
   stays stale.
4. **A success-only marker**, so a failed pass is retried on the next open and
   never recorded as done.

:func:`rewrite_values` is the primitive: ``fn(body) -> body``, applied to every
annotation body in every scope of the project. It works through the project's
:class:`~nw.storage.ProjectStorage` (a path, a storage, or an :class:`nw.Project`),
so a mapping-backed genre project is rewritten like a folder one. The marker lives
in the storage's ``docs`` under :data:`MARKER_PREFIX`.

Two passes, traces first: a crash between them leaves the old bodies in place, so
a retry still finds them (the traces already hold the new digests and are skipped)
and the body pass then makes dependents fresh again. Bodies are rewritten from the
row as just read, so a write that landed since the plan was made is kept.

``fn`` must be pure and idempotent (it runs again on retry), and must return a new
body or an equal one; returning an unchanged body leaves the row untouched. It may
change *values* but not identity: annotation ids, provenance and timestamps are
kept, because a rename is not a change of look.
"""

from __future__ import annotations

import copy
from contextlib import suppress
import logging
import re
from collections.abc import Callable, Mapping
from typing import Any
from uuid import UUID


from . import _freshness_pass
from .bodies.genre_envelope import GENRE_ENVELOPE_TIER, GenreEnvelopeBodyV1
from .bodies.verifying_trace import (
    VERIFYING_TRACE_BODY_SCHEMA_URI,
    digest_vouches,
    recorded_exclusions,
    upstream_entry,
)
from .storage import ProjectLike, as_project_storage, project_lock
from lacing.digest import VALUE_DIGEST_SCHEME, VALUE_DIGEST_SCHEMES

_logger = logging.getLogger(__name__)

MARKER_PREFIX = ".nw/rewrites/"
"""Key prefix, in ``storage.docs``, of the success markers (``<prefix><name>.json``)."""

LOCK_NAME = "rewrite-values"
"""The one :func:`~nw.storage.project_lock` every rewrite takes. Not per marker:
two different rewrites planning from the same original bodies would each
invalidate the other's digests."""

MARKER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]*")
"""What a marker name may be: a slug, so it cannot escape :data:`MARKER_PREFIX`."""


def is_value_row(ann: Any) -> bool:
    """The default ``where``: every annotation except nw's verifying traces.

    A trace's body is nw's bookkeeping (digests, ``for_annotation_id``), not a
    stored value; a generic ``fn`` walking it would corrupt it, and the re-stamp
    is what keeps it right.
    """
    return ann.body_schema_uri != VERIFYING_TRACE_BODY_SCHEMA_URI


def rewrite_values(
    project: ProjectLike,
    fn: Callable[[Any], Any],
    *,
    marker: str | None = None,
    where: Callable[[Any], bool] = is_value_row,
) -> int:
    """Apply ``fn(body) -> body`` to every stored annotation body; return how many changed.

    ``marker`` names a one-time rewrite: when its marker exists nothing runs
    (``0``); otherwise the lock is taken, the marker re-checked, the rewrite run,
    and the marker written only after the pass finished cleanly. ``None`` runs
    every time, under a lock of its own name, with no marker (idempotent ``fn``
    makes that safe).

    ``where(annotation) -> bool`` picks the rows ``fn`` sees (default: everything
    but verifying traces; ``fn`` can branch on ``body_schema_uri`` / tier there
    instead of guessing from field names). ``fn`` gets a private copy of the body,
    so mutating it in place is safe; return the new body.

    With ``marker=None`` there is no done-record, so a caller must retry a raised
    failure itself: the trace pass lands first, and until the body pass finishes
    dependents read stale. A writer that does not take this lock and lands a trace
    mid-rewrite leaves that trace stale (conservative, never wrong-fresh).

    ``project`` is a path, a :class:`~nw.storage.ProjectStorage` or an
    :class:`nw.Project`; ``marker`` a slug (:data:`MARKER_PATTERN`).
    """
    key = _marker_key(marker) if marker is not None else None
    storage = as_project_storage(project)
    if key is not None and key in storage.docs:
        return 0
    with project_lock(storage, LOCK_NAME):
        if key is not None and key in storage.docs:
            return 0
        changed = _rewrite(storage, fn, where)
        if key is not None:
            storage.docs[key] = {"rewritten": changed}
    return changed


TRACE_UPGRADE_MARKER = "traces-on-current-digest-scheme"
"""The marker :func:`upgrade_superseded_traces` records once a project's traces
are all on today's digest scheme (bump it if the scheme moves again)."""


def upgrade_superseded_traces(
    project: ProjectLike, *, marker: str | None = TRACE_UPGRADE_MARKER
) -> int:
    """Re-record every verifying trace that is on a superseded digest scheme, or
    whose entries are not what nw records today, **while it still vouches** for
    its parents' current values; return how many traces moved (nw#226).

    Per trace: an entry equal to :func:`~nw.bodies.verifying_trace.upstream_entry`
    today (digest and ``excluded_paths`` together) is kept; one whose recorded
    digest still describes the parent
    (:func:`~nw.bodies.verifying_trace.digest_vouches` under the entry's scheme
    and exclusions) is re-recorded as ``upstream_entry`` records it; any other
    entry means the trace is already stale, and it is left alone (never
    blessed). So a fresh dependent stays fresh and a stale one stays stale.

    Why: a trace recorded under an old scheme digests the whole body, so a later
    fill of a ``Derived`` field (a panel image's ``asset_id``) reads as an
    upstream change, and each host repaired that per write (reelee's
    ``_upgrade_traces``). Run once per project, it never meets the fill.

    Idempotent; with ``marker`` (the default) it runs at most once per project,
    under the same lock and marker discipline as :func:`rewrite_values`;
    ``marker=None`` runs every time.
    """
    key = _marker_key(marker) if marker is not None else None
    storage = as_project_storage(project)
    if key is not None and key in storage.docs:
        return 0
    with project_lock(storage, LOCK_NAME):
        if key is not None and key in storage.docs:
            return 0
        _freshness_pass.forget()
        try:
            moved = _upgrade_traces(storage)
        finally:
            _freshness_pass.forget()
        if key is not None:
            storage.docs[key] = {"rewritten": moved}
    return moved


def _upgraded_upstream(body: Mapping, by_id: Mapping[UUID, Any], today_of=None):
    """``body``'s upstream as nw records it today, or ``None`` when nothing moves
    or the trace is stale (or names a parent that is gone). ``today_of(parent)``
    is :func:`upstream_entry` under today's scheme, memoized by the caller."""
    today_of = today_of or (lambda p: upstream_entry(p, scheme=VALUE_DIGEST_SCHEME))
    scheme = body.get("digest_scheme")
    if scheme not in VALUE_DIGEST_SCHEMES:
        return None
    moved = scheme != VALUE_DIGEST_SCHEME
    upstream = []
    for entry in body.get("upstream") or ():
        try:
            parent = by_id[UUID(str(entry["annotation_id"]))]
        except (KeyError, ValueError, TypeError):
            return None
        today = today_of(parent)
        if entry.get("value_digest") == today["value_digest"] and recorded_exclusions(
            entry
        ) == recorded_exclusions(today):
            upstream.append({"annotation_id": entry["annotation_id"], **today})
            continue
        reentered = _reentered(
            entry, vouches_for=parent, recorded_scheme=scheme, today=lambda: today
        )
        if reentered is None:
            return None  # already stale: not ours to freshen
        upstream.append(reentered)
        moved = True
    return upstream if moved else None


def _upgrade_traces(storage) -> int:
    from .graph import iter_all_annotations

    by_id = {a.id: a for a in iter_all_annotations(storage)}
    todays: dict = {}

    def today_of(parent):  # a parent with many children is digested once
        if parent.id not in todays:
            todays[parent.id] = upstream_entry(parent, scheme=VALUE_DIGEST_SCHEME)
        return todays[parent.id]

    moved = 0
    with storage.open_stores() as stores:
        for store in stores:
            for ann in list(store.all()):
                if ann.body_schema_uri != VERIFYING_TRACE_BODY_SCHEMA_URI:
                    continue
                # One bad row (a parent outside the JSON contract, a trace a
                # concurrent writer replaced) must not stop the rest, nor keep
                # the marker from being written; left as it is, a trace is at
                # worst stale, never wrong-fresh.
                try:
                    upstream = _upgraded_upstream(ann.body, by_id, today_of)
                    if upstream is None:
                        continue
                    body = {
                        **ann.body,
                        "digest_scheme": VALUE_DIGEST_SCHEME,
                        "upstream": upstream,
                    }
                    store.update(ann.model_copy(update={"body": body}))
                    moved += 1
                except Exception:
                    _logger.warning(
                        "upgrade_superseded_traces: left trace %s as it is",
                        ann.id,
                        exc_info=True,
                    )
    return moved


def is_rewritten(project: ProjectLike, marker: str) -> bool:
    """Whether the rewrite named ``marker`` has completed on this project."""
    return _marker_key(marker) in as_project_storage(project).docs


def mark_rewritten(project: ProjectLike, marker: str) -> None:
    """Record ``marker`` as done without scanning: for a project created already
    in today's vocabulary, so opening it never pays for the scan."""
    as_project_storage(project).docs[_marker_key(marker)] = {"rewritten": 0}


def unmark_rewritten(project: ProjectLike, marker: str) -> None:
    """Forget that ``marker`` ran, so the next :func:`rewrite_values` with it scans
    again (a test simulating a project made before the rename). Idempotent: an
    absent marker is not an error and writes nothing. A present one is removed
    under :data:`LOCK_NAME`, so a rewrite about to write it cannot undo the
    removal; its value is never read, so a corrupt marker can be cleared too."""
    key = _marker_key(marker)
    storage = as_project_storage(project)
    if key not in storage.docs:
        return
    with project_lock(storage, LOCK_NAME):
        try:
            del storage.docs[key]
        except KeyError:
            # dol reports any failed file delete as ``KeyError``; only a marker
            # another unmark already removed may pass.
            if key in storage.docs:
                raise


def _marker_key(marker: str) -> str:
    if not MARKER_PATTERN.fullmatch(marker):
        raise ValueError(
            f"marker must match {MARKER_PATTERN.pattern!r}, got {marker!r}"
        )
    return f"{MARKER_PREFIX}{marker}.json"


def _rewritten(ann: Any, fn, where) -> Any:
    """``ann`` with ``fn`` applied to a private copy of its body, or ``None`` if
    ``where`` skips it or the body comes back equal."""
    if not where(ann):
        return None
    new_body = fn(copy.deepcopy(ann.body))
    return None if new_body == ann.body else ann.model_copy(update={"body": new_body})


def _rewrite(storage, fn: Callable[[Any], Any], where) -> int:
    # A value rewritten in place no longer matches what an open freshness
    # pass holds for its tier, nor (re-stamped traces aside) its walk:
    # every pass drops them, before and after (nw#209).
    _freshness_pass.forget()
    try:
        return _rewrite_stores(storage, fn, where)
    finally:
        _freshness_pass.forget()


def _rewrite_stores(storage, fn: Callable[[Any], Any], where) -> int:
    plan: dict[
        UUID, tuple[Any, Any]
    ] = {}  # id -> (old annotation, rewritten annotation)
    with storage.open_stores() as stores:
        for store in stores:
            for ann in store.all():
                new = _rewritten(ann, fn, where)
                if new is not None:
                    plan[ann.id] = (ann, new)
    if not plan:
        return 0
    with storage.open_stores() as stores:
        for store in stores:
            for ann in list(store.all()):
                restamped = _restamped_trace(ann, plan)
                if restamped is not None:
                    store.update(restamped)
    written = 0
    envelope = None
    with storage.open_stores() as stores:
        for store in stores:
            for ann in list(store.all()):
                new = _rewritten(ann, fn, where)
                if new is not None:
                    store.update(new)
                    written += 1
                    if new.tier == GENRE_ENVELOPE_TIER:
                        envelope = new
    if envelope is not None:
        # The envelope's document mirror (nw#223) must follow a rename too, or
        # nw.project_genre keeps answering the old slug.
        from .graph import mirror_genre_envelope

        with suppress(Exception):
            mirror_genre_envelope(
                storage, GenreEnvelopeBodyV1.model_validate(envelope.body)
            )
    return written


def _reentered(
    entry: Mapping,
    *,
    vouches_for: Any,
    recorded_scheme: str,
    today: Callable[[], dict],
) -> dict | None:
    """``entry`` re-recorded as ``today()`` — if its digest, read under
    ``recorded_scheme`` and its recorded exclusions, still vouches for
    ``vouches_for``'s value; ``None`` when it does not (the trace is stale
    there, and no one may freshen it). The one vouch-then-re-record step of
    :func:`rewrite_values` (vouch for the old body, record the new one) and
    :func:`upgrade_superseded_traces` (vouch for and record the same parent
    under today's scheme), nw#273. ``today`` is called only after a vouch.

    Only the parent's id carries over: a field a newer nw added refines the OLD
    digest, not this one.
    """
    if not digest_vouches(
        vouches_for,
        entry.get("value_digest"),
        scheme=recorded_scheme,
        excluded=recorded_exclusions(entry),
    ):
        return None
    return {"annotation_id": entry["annotation_id"], **today()}


def _restamped_trace(ann: Any, plan: Mapping[UUID, tuple[Any, Any]]) -> Any:
    """``ann`` (a verifying trace) with each upstream digest of a rewritten annotation
    moved from the old body's digest to the new one's; ``None`` when nothing moves."""
    if ann.body_schema_uri != VERIFYING_TRACE_BODY_SCHEMA_URI:
        return None
    body = ann.body
    scheme = body.get("digest_scheme")
    upstream = []
    moved = False
    for entry in body.get("upstream") or ():
        try:
            old, new = plan[UUID(entry["annotation_id"])]
            # Any digest that still vouches for the old body moves, including
            # one recorded before a Derived marker or under fewer of them
            # (nw#179, nw#180); it is re-recorded with today's exclusions.
            reentered = _reentered(
                entry,
                vouches_for=old,
                recorded_scheme=scheme,
                today=lambda: upstream_entry(new, scheme=scheme),
            )
            if reentered is not None:
                entry, moved = reentered, True
        except (KeyError, ValueError, TypeError):
            pass
        upstream.append(entry)
    return (
        ann.model_copy(update={"body": {**body, "upstream": upstream}})
        if moved
        else None
    )
