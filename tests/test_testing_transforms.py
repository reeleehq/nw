"""nw.testing.transforms: a result's written/reused_ids are checked against the graph (nw#234)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from nw.testing.transforms import recording_writes
from tests.test_fresh_equivalents import (  # noqa: F401 — `fal` is a fixture
    _Reusing,
    _plan,
    _project,
    _skeleton,
    fal,
)


def test_the_default_execute_is_honest_when_writing_and_when_reusing(tmp_path, fal):
    proj, (shot,) = _project(tmp_path)
    with recording_writes(proj) as writes:
        first = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))
    writes.check(first)
    assert first.written and not first.reused_ids

    with recording_writes(proj) as writes:
        second = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))
    writes.check(second)
    assert second.reused_ids and not second.written


def test_an_override_returning_an_existing_node_as_written_is_caught(tmp_path, fal):
    """The case nw#215 made an obligation: an existing node returned without
    being reported in reused_ids reads as written, and the check says so."""
    proj, (shot,) = _project(tmp_path)
    first = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))
    with recording_writes(proj) as writes:
        lying = replace(first, reused_ids=frozenset())  # returned again, unreported
    with pytest.raises(AssertionError, match="reported written, not written"):
        writes.check(lying)


def test_claiming_reuse_of_a_node_written_in_the_call_is_caught(tmp_path, fal):
    proj, (shot,) = _project(tmp_path)
    with recording_writes(proj) as writes:
        result = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))
    lying = replace(result, reused_ids=frozenset(a.id for a in result.annotations))
    with pytest.raises(AssertionError, match="reported reused, but written"):
        writes.check(lying)


def test_a_reused_id_must_be_among_the_annotations(tmp_path, fal):
    from uuid import uuid4

    proj, (shot,) = _project(tmp_path)
    with recording_writes(proj) as writes:
        result = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))
    with pytest.raises(AssertionError, match="not among result.annotations"):
        writes.check(replace(result, reused_ids=frozenset({uuid4()})))


def test_a_derived_node_rewritten_unchanged_counts_as_written(tmp_path, fal):
    """The trace branch: remove + re-add of the same derived node inside the
    block is a write (a fresh trace names it), so reporting it reused lies."""
    proj, (shot,) = _project(tmp_path)
    first = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))
    (node,) = first.annotations
    with recording_writes(proj) as writes:
        proj.graph.remove_annotation(node.id)
        proj.graph.add_annotation(node)
    writes.check(replace(first, reused_ids=frozenset()))  # written: true
    with pytest.raises(AssertionError, match="reported reused, but written"):
        writes.check(replace(first, reused_ids=frozenset({node.id})))


def test_writes_after_the_block_do_not_count(tmp_path, fal):
    proj, (shot,) = _project(tmp_path)
    with recording_writes(proj) as writes:
        pass
    result = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))
    with pytest.raises(AssertionError, match="reported written, not written"):
        writes.check(result)


def test_require_traces_flags_a_derived_row_written_behind_add_annotation(tmp_path, fal):
    """nw#271: a raw store.add leaves no trace; such a row reads stale forever."""
    import nw

    proj, (shot,) = _project(tmp_path)
    with recording_writes(proj) as writes:
        honest = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))
    writes.check(honest, require_traces=True)

    raw = _skeleton(proj, (shot,), shot_id="raw")
    with recording_writes(proj) as writes:
        with proj.storage.open_stores() as stores:
            next(iter(stores)).add(raw)
    lying = replace(honest, annotations=(raw,), reused_ids=frozenset())
    writes.check(lying, require_traces=False)  # written, truthfully
    with pytest.raises(AssertionError, match="no verifying trace"):
        writes.check(lying)  # traces are required by default


def test_a_derived_row_whose_parent_is_in_no_store_has_no_trace(tmp_path, fal):
    """add_annotation writes no trace when it cannot resolve a parent: still a
    row that reads stale forever, and the message names that cause too."""
    from uuid import uuid4

    proj, (shot,) = _project(tmp_path)
    orphan = _skeleton(proj, (uuid4(),), shot_id="orphan")  # parent exists nowhere
    with recording_writes(proj) as writes:
        proj.graph.add_annotation(orphan)
    result = replace(
        _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),)),
        annotations=(orphan,), reused_ids=frozenset(),
    )
    with pytest.raises(AssertionError, match="could not resolve or digest a parent"):
        writes.check(result)
