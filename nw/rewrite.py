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
import logging
import re
from collections.abc import Callable, Mapping
from typing import Any
from uuid import UUID

from lacing.digest import annotation_value_digest

from .bodies.verifying_trace import VERIFYING_TRACE_BODY_SCHEMA_URI
from .storage import ProjectLike, as_project_storage, project_lock

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


def is_rewritten(project: ProjectLike, marker: str) -> bool:
    """Whether the rewrite named ``marker`` has completed on this project."""
    return _marker_key(marker) in as_project_storage(project).docs


def mark_rewritten(project: ProjectLike, marker: str) -> None:
    """Record ``marker`` as done without scanning: for a project created already
    in today's vocabulary, so opening it never pays for the scan."""
    as_project_storage(project).docs[_marker_key(marker)] = {"rewritten": 0}


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
    with storage.open_stores() as stores:
        for store in stores:
            for ann in list(store.all()):
                new = _rewritten(ann, fn, where)
                if new is not None:
                    store.update(new)
                    written += 1
    return written


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
            if entry["value_digest"] == annotation_value_digest(old, scheme=scheme):
                entry = {
                    **entry,
                    "value_digest": annotation_value_digest(new, scheme=scheme),
                }
                moved = True
        except (KeyError, ValueError, TypeError):
            pass
        upstream.append(entry)
    return (
        ann.model_copy(update={"body": {**body, "upstream": upstream}})
        if moved
        else None
    )
