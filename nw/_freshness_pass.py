"""The state a :func:`nw.freshness.freshness_pass` holds, and how writes drop it.

Private, and separate from :mod:`nw.freshness` for one reason: the writers
that must drop the held state (:mod:`nw.graph`, :mod:`nw.rewrite`) are
imported *by* :mod:`nw.freshness`, so they cannot import it back. Both sides
import this leaf module instead. The rule is
:func:`nw.freshness.freshness_pass`'s docstring; this module is its
mechanism.

Two pieces, deliberately different in scope:

- **The pass** is per context (a :mod:`contextvars` variable): one dict,
  keyed by :func:`root_key`, whose per-project entries the reader fills
  lazily (``"tiers"``: ``{tier: [annotations]}``; ``"fresh"``: the ids the
  snapshot walk verified fresh). Nothing here walks or reads a store.
- **The write epoch** is process-wide. A write in *any* thread — a request
  thread editing a shot while a fan-out runs on a worker that did not copy
  this context — bumps it, and an entry filled under an older epoch is
  discarded on its next use. A writer cannot reach the pass's dict (it lives
  in another context), which is why invalidation is a counter the reader
  compares against rather than a delete the writer performs. It over-drops
  across projects (any write drops every held walk), which is safe.
"""

from __future__ import annotations

import itertools
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Optional

_PASS: ContextVar[Optional[dict]] = ContextVar("nw_freshness_pass", default=None)
"""``{root_key: {"epoch": int, "data": dict}}`` while a pass is open, else
``None``."""

_EPOCHS = itertools.count()
_epoch_lock = threading.Lock()
_epoch = next(_EPOCHS)
"""The current write epoch: a value no earlier write left behind."""


def root_key(project) -> str:
    """The key a project's held state is filed under: its resolved root.

    ``project`` is anything :func:`nw.storage.as_project_storage` accepts, so
    a path, an ``nw.Project`` and any storage over the same root share a key
    — two storages over one root are one project here.
    """
    from .storage import as_project_storage

    return str(Path(as_project_storage(project).root).resolve())


@contextmanager
def open_pass() -> Iterator[None]:
    """Open a pass in this context, or join the one already open (nested
    passes share the outermost). Reads nothing."""
    if _PASS.get() is not None:
        yield
        return
    token = _PASS.set({})
    try:
        yield
    finally:
        _PASS.reset(token)


def held(project) -> Optional[dict]:
    """The open pass's state for ``project`` — a dict the caller fills — or
    ``None`` when no pass is open in this context.

    Created empty, and recreated empty whenever a write has happened since it
    was created (the epoch moved). The epoch is read *before* anything is
    filled, so a write racing the fill leaves the entry stamped with the
    older epoch, and the next use discards it.
    """
    state = _PASS.get()
    if state is None:
        return None
    now = _epoch
    key = root_key(project)
    entry = state.get(key)
    if entry is None or entry["epoch"] != now:
        entry = state[key] = {"epoch": now, "data": {}}
    return entry["data"]


def forget() -> None:
    """Record that a write which can change freshness or a tier's contents
    happened (or is about to): every held walk, in every context, is dropped
    on its next use.

    Unconditional and cheap — no early return when this context has no pass,
    because the pass that must hear about it may be in another thread's
    context. Writers call it before and after the write, so neither a reader
    filling during the write nor one starting right after it keeps an answer
    from before it.
    """
    global _epoch
    with _epoch_lock:
        _epoch = next(_EPOCHS)
