"""The state a :func:`nw.freshness.freshness_pass` holds, and how writes drop it.

Private, and separate from :mod:`nw.freshness` for one reason: the writers
that must drop the held state (:mod:`nw.graph`, :mod:`nw.rewrite`) are
imported *by* :mod:`nw.freshness`, so they cannot import it back. Both sides
import this leaf module instead. The rule and the public seam are
:func:`nw.freshness.freshness_pass`'s docstring.

The held state is one mutable dict per open pass, keyed by
:func:`root_key`, whose values are per-project dicts the reader fills in
lazily (``"tiers"``: ``{tier: [annotations]}``; ``"fresh"``: the ids the
snapshot walk verified fresh). Nothing here walks or reads a store.
"""

from __future__ import annotations

from contextvars import ContextVar
from pathlib import Path
from typing import Optional

_PASS: ContextVar[Optional[dict]] = ContextVar("nw_freshness_pass", default=None)
"""``{root_key: {...held state...}}`` while a pass is open, else ``None``."""


def root_key(project) -> str:
    """The key a project's held state is filed under: its resolved root.

    ``project`` is anything :func:`nw.storage.as_project_storage` accepts, so
    a path, an ``nw.Project`` and a storage over the same root share a key.
    """
    from .storage import as_project_storage

    return str(Path(as_project_storage(project).root).resolve())


def held(project) -> Optional[dict]:
    """The open pass's state for ``project`` (created empty), or ``None``
    when no pass is open."""
    state = _PASS.get()
    if state is None:
        return None
    return state.setdefault(root_key(project), {})


def forget(project=None) -> None:
    """Drop the held state for ``project`` — or for every project when
    ``project`` is ``None`` (a writer that only has a store, not a root).

    Called by every nw write path that can change an existing node's
    freshness or a tier's contents. Free when no pass is open, or when the
    open pass holds nothing yet: nothing is resolved then.
    """
    state = _PASS.get()
    if not state:
        return
    if project is None:
        state.clear()
    else:
        state.pop(root_key(project), None)
