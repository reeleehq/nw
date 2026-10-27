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

import logging
from collections.abc import Callable, Mapping
from typing import Any
from uuid import UUID

from lacing.digest import annotation_value_digest

from .bodies.verifying_trace import VERIFYING_TRACE_BODY_SCHEMA_URI
from .storage import ProjectLike, as_project_storage, project_lock

_logger = logging.getLogger(__name__)

MARKER_PREFIX = ".nw/rewrites/"
"""Key prefix, in ``storage.docs``, of the success markers (``<prefix><name>.json``)."""

LOCK_PREFIX = "rewrite-values:"
"""Prefix of the :func:`~nw.storage.project_lock` name taken for a marker."""


def rewrite_values(
    project: ProjectLike,
    fn: Callable[[Any], Any],
    *,
    marker: str | None = None,
) -> int:
    """Apply ``fn(body) -> body`` to every stored annotation body; return how many changed.

    ``marker`` names a one-time rewrite: when its marker exists nothing runs
    (``0``); otherwise the lock is taken, the marker re-checked, the rewrite run,
    and the marker written only after the pass finished cleanly. ``None`` runs
    every time, under a lock of its own name, with no marker (idempotent ``fn``
    makes that safe).

    ``project`` is a path, a :class:`~nw.storage.ProjectStorage` or an
    :class:`nw.Project`.
    """
    storage = as_project_storage(getattr(project, "storage", project))
    key = None if marker is None else f"{MARKER_PREFIX}{marker}.json"
    if key is not None and key in storage.docs:
        return 0
    with project_lock(storage, f"{LOCK_PREFIX}{marker or ''}"):
        if key is not None and key in storage.docs:
            return 0
        changed = _rewrite(storage, fn)
        if key is not None:
            storage.docs[key] = {"rewritten": changed}
    return changed


def is_rewritten(project: ProjectLike, marker: str) -> bool:
    """Whether the rewrite named ``marker`` has completed on this project."""
    storage = as_project_storage(getattr(project, "storage", project))
    return f"{MARKER_PREFIX}{marker}.json" in storage.docs


def _rewrite(storage, fn: Callable[[Any], Any]) -> int:
    plan: dict[UUID, tuple[Any, Any]] = {}  # id -> (old annotation, rewritten annotation)
    with storage.open_stores() as stores:
        for store in stores:
            for ann in store.all():
                new_body = fn(ann.body)
                if new_body != ann.body:
                    plan[ann.id] = (ann, ann.model_copy(update={"body": new_body}))
    if not plan:
        return 0
    with storage.open_stores() as stores:
        for store in stores:
            for ann in list(store.all()):
                restamped = _restamped_trace(ann, plan)
                if restamped is not None:
                    store.update(restamped)
    with storage.open_stores() as stores:
        for store in stores:
            for ann in list(store.all()):
                new_body = fn(ann.body)
                if new_body != ann.body:
                    store.update(ann.model_copy(update={"body": new_body}))
    return len(plan)


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
                entry = {**entry, "value_digest": annotation_value_digest(new, scheme=scheme)}
                moved = True
        except (KeyError, ValueError, TypeError):
            pass
        upstream.append(entry)
    return ann.model_copy(update={"body": {**body, "upstream": upstream}}) if moved else None
