"""Conformance check: a Transform's result says truthfully what it wrote (nw#234).

:attr:`nw.transforms.TransformResult.reused_ids` is an **obligation** on an
overriding ``execute``: report every returned node it did not write in this
call (nw#215). nw cannot check that at runtime (overrides legitimately mint
ids), but a Transform author's test can::

    from nw.testing.transforms import recording_writes

    with recording_writes(project) as writes:
        result = my_transform.execute(project, plan, skeleton)
    writes.check(result)  # AssertionError naming every misreported row

A row counts as **written in the call** when its id is new, its content changed
(body, generation stamp or tier: an in-place entity upsert counts), or a
verifying trace naming it was recorded during the call (a derived node
re-written unchanged; nw's ``add_annotation`` records one per write, under a
fresh id). What counts is fixed when the ``with`` block exits.
:meth:`WriteRecord.check` asserts every ``result.written`` row was, and every
``result.reused_ids`` row was not. Run it over a host's registered Transforms,
the way nw pins every ``execute`` signature.

To check **every** overriding ``execute`` a suite runs, with no test of its own
per Transform, put one line in ``conftest.py`` (nw#281)::

    from nw.testing.transforms import make_truthful_writes_fixture

    truthful_writes = make_truthful_writes_fixture()

It wraps the ``execute`` of each class that owns a registered Transform's
``execute`` and fails the test at teardown with every misreport, so a caller's
broad ``except`` cannot swallow the lie and a Transform added later is covered.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import json
from collections.abc import Mapping
from typing import Iterator, Optional
from uuid import UUID

__all__ = ["WriteRecord", "make_truthful_writes_fixture", "recording_writes"]

REQUIRE_TRACES_MODES = (True, False, "resolvable")
"""``require_traces`` values: ``True`` (every written derived row must have a
trace), ``False`` (never), ``"resolvable"`` (only a row whose annotation
parents are all in the graph: one that cannot be traced is not a defect)."""


@dataclass(frozen=True)
class _Snapshot:
    rows: Mapping[UUID, str]  # id -> fingerprint of what the row holds
    trace_ids: frozenset[UUID]


def _fingerprint(ann) -> str:
    return json.dumps(
        [ann.body, str(ann.provenance.generated_at_time), ann.tier],
        sort_keys=True,
        default=str,
    )


def _snapshot(project) -> _Snapshot:
    from nw.bodies import VERIFYING_TRACE_TIER
    from nw.graph import iter_all_annotations

    anns = list(iter_all_annotations(project))
    return _Snapshot(
        rows={a.id: _fingerprint(a) for a in anns},
        trace_ids=frozenset(a.id for a in anns if a.tier == VERIFYING_TRACE_TIER),
    )


def _new_trace_targets(project, before: _Snapshot) -> frozenset[UUID]:
    from nw.bodies import VERIFYING_TRACE_TIER
    from nw.graph import annotations_at_tier

    return frozenset(
        UUID(str(t.body.get("for_annotation_id")))
        for t in annotations_at_tier(project, VERIFYING_TRACE_TIER)
        if t.id not in before.trace_ids and t.body.get("for_annotation_id")
    )


@dataclass
class WriteRecord:
    """What :func:`recording_writes` saw: the project on entry and, once the
    block has exited, what was written inside it."""

    project: object
    before: _Snapshot = field(repr=False)
    _written: Optional[frozenset] = field(default=None, repr=False)

    def written_in_call(self) -> frozenset[UUID]:
        """Ids written inside the block: new, changed (body, stamp or tier), or
        re-written unchanged (a fresh verifying trace names them). Fixed when the
        block exits; computed live while still inside it."""
        if self._written is not None:
            return self._written
        now = _snapshot(self.project)
        changed = {i for i, fp in now.rows.items() if self.before.rows.get(i) != fp}
        return frozenset(changed) | _new_trace_targets(self.project, self.before)

    def _ids_now(self) -> frozenset[UUID]:
        return frozenset(_snapshot(self.project).rows)

    def check(self, result, *, require_traces: "bool | str" = True) -> None:
        """Raise ``AssertionError`` unless ``result.written`` / ``result.reused_ids``
        tell the truth (a real raise, so ``python -O`` cannot skip it).

        ``require_traces`` (default ``True``) also flags a written **derived**
        row (one with ``was_derived_from`` parents) that got no verifying trace
        in the block: written by a raw ``store.add``, or by ``add_annotation``
        with a parent it could not resolve or digest, it reads stale forever
        (nw#271). Only rows the result reports are scanned; a derived row
        written but not reported is out of this check's reach.

        ``require_traces="resolvable"`` (nw#281) asks for that trace only when
        every annotation parent of the row is in the graph: a unit scenario
        that never adds the parents cannot be traced, so unconditionally
        requiring it flags no production bug, while turning it off no longer
        catches a raw ``store.add``."""
        if require_traces not in REQUIRE_TRACES_MODES:
            raise ValueError(
                f"require_traces must be one of {REQUIRE_TRACES_MODES}, "
                f"not {require_traces!r}"
            )
        written = self.written_in_call()
        claimed_written = {a.id for a in result.written}
        lies = (
            [
                f"{i}: reported written, not written in this call"
                for i in claimed_written - written
            ]
            + [
                f"{i}: reported reused, but written in this call"
                for i in set(result.reused_ids) & written
            ]
            + [
                f"{i}: reported reused, but not among result.annotations"
                for i in set(result.reused_ids) - {a.id for a in result.annotations}
            ]
        )
        if require_traces:
            traced = _new_trace_targets(self.project, self.before)
            in_graph = (
                self._ids_now() if require_traces == "resolvable" else frozenset()
            )
            lies += [
                f"{a.id}: derived row has no verifying trace (a raw store.add, or "
                "add_annotation could not resolve or digest a parent); reads stale forever"
                for a in result.written
                if a.provenance.was_derived_from
                and a.id not in traced
                and (require_traces is True or _parents_resolve(a, in_graph))
            ]
        lies.sort()
        if lies:
            raise AssertionError(
                "TransformResult does not hold up:\n  " + "\n  ".join(lies)
            )


def _parents_resolve(ann, ids_in_graph) -> bool:
    """Whether every annotation parent of ``ann`` is in the graph."""
    from lacing.model import partition_provenance_refs

    parents, _assets = partition_provenance_refs(list(ann.provenance.was_derived_from))
    return all(p in ids_in_graph for p in parents)


@contextmanager
def recording_writes(project) -> Iterator[WriteRecord]:
    """Snapshot ``project`` now and, on exit, what the block wrote;
    :meth:`WriteRecord.check` a result made inside."""
    record = WriteRecord(project=project, before=_snapshot(project))
    try:
        yield record
    finally:
        record._written = record.written_in_call()


def _execute_owners(owner_filter) -> list[type]:
    """Classes that own a registered Transform's ``execute`` (found through the MRO)."""
    from nw.transforms import transforms

    owners: dict[type, None] = {}
    for name in list(transforms):
        for cls in type(transforms[name]).__mro__:
            if "execute" in vars(cls):
                if owner_filter(cls):
                    owners[cls] = None
                break
    return list(owners)


def make_truthful_writes_fixture(
    *,
    owner_filter=lambda cls: True,
    require_traces: "bool | str" = "resolvable",
    autouse: bool = True,
):
    """A pytest fixture checking every registered Transform's ``execute`` (nw#281).

    Like ``falaw.testing.make_fake_assets_fixture``: call it in ``conftest.py``
    and bind the result to a name. While a test runs, the ``execute`` of each
    class that owns a registered Transform's ``execute`` is wrapped in
    :func:`recording_writes`; at teardown every misreport is raised together as
    one ``AssertionError``. A nested ``execute`` (a ``super().execute`` call)
    is checked once, at the outermost call. Only results that carry
    ``written`` / ``reused_ids`` are checked.

    ``owner_filter(cls) -> bool`` narrows which classes are wrapped (e.g. only
    the host's own package); ``require_traces`` is passed to
    :meth:`WriteRecord.check`, default ``"resolvable"``.
    """
    import functools
    import threading

    import pytest

    depth = threading.local()

    @pytest.fixture(autouse=autouse)
    def truthful_writes():
        owners = _execute_owners(owner_filter)
        saved = {cls: vars(cls)["execute"] for cls in owners}
        checked: list[tuple[WriteRecord, object]] = []

        def wrap(orig):
            @functools.wraps(orig)
            def execute(self, project, *args, **kwargs):
                if getattr(depth, "n", 0):
                    return orig(self, project, *args, **kwargs)
                depth.n = 1
                try:
                    with recording_writes(project) as record:
                        result = orig(self, project, *args, **kwargs)
                finally:
                    depth.n = 0
                if hasattr(result, "written") and hasattr(result, "reused_ids"):
                    checked.append((record, result))
                return result

            return execute

        for cls, orig in saved.items():
            cls.execute = wrap(orig)
        try:
            yield
        finally:
            for cls, orig in saved.items():
                cls.execute = orig
        problems = []
        for record, result in checked:
            try:
                record.check(result, require_traces=require_traces)
            except AssertionError as e:
                problems.append(str(e))
        if problems:
            raise AssertionError("\n".join(problems))

    return truthful_writes
