"""Conformance check: a Transform's result says truthfully what it wrote (nw#234).

:attr:`nw.transforms.TransformResult.reused_ids` is an **obligation** on an
overriding ``execute``: report every returned node it did not write in this
call (nw#215). nw cannot check that at runtime (overrides legitimately mint
ids), but a Transform author's test can::

    from nw.testing.transforms import recording_writes

    with recording_writes(project) as writes:
        result = my_transform.execute(project, plan, skeleton)
    writes.check(result)  # AssertionError naming every misreported row

A row counts as **written in the call** when its id was not in the project
before, or a verifying trace naming it was recorded during the call (nw's
``add_annotation`` records one per write of a derived node, under a fresh id).
:meth:`WriteRecord.check` asserts every ``result.written`` row was, and every
``result.reused_ids`` row was not. Run it over a host's registered Transforms,
the way nw pins every ``execute`` signature.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Iterator
from uuid import UUID

__all__ = ["WriteRecord", "recording_writes"]


@dataclass(frozen=True)
class _Snapshot:
    ids: frozenset[UUID]
    trace_ids: frozenset[UUID]


def _snapshot(project) -> _Snapshot:
    from nw.bodies import VERIFYING_TRACE_TIER
    from nw.graph import iter_all_annotations

    anns = list(iter_all_annotations(project))
    return _Snapshot(
        ids=frozenset(a.id for a in anns),
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
    """What the project held when :func:`recording_writes` was entered."""

    project: object
    before: _Snapshot = field(repr=False)

    def written_in_call(self) -> frozenset[UUID]:
        """Ids new since entry, or re-written (a fresh trace names them)."""
        now = _snapshot(self.project)
        return (now.ids - self.before.ids) | _new_trace_targets(self.project, self.before)

    def check(self, result) -> None:
        """Assert ``result.written`` / ``result.reused_ids`` tell the truth."""
        written = self.written_in_call()
        claimed_written = {a.id for a in result.written}
        lies = sorted(
            [f"{i}: reported written, not written in this call" for i in claimed_written - written]
            + [f"{i}: reported reused, but written in this call" for i in set(result.reused_ids) & written]
            + [f"{i}: reported reused, but not among result.annotations"
               for i in set(result.reused_ids) - {a.id for a in result.annotations}]
        )
        assert not lies, "TransformResult misreports what it wrote:\n  " + "\n  ".join(lies)


@contextmanager
def recording_writes(project) -> Iterator[WriteRecord]:
    """Snapshot ``project`` now; :meth:`WriteRecord.check` a result made inside."""
    yield WriteRecord(project=project, before=_snapshot(project))
