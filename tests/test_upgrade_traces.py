"""nw.upgrade_superseded_traces: old-scheme traces re-recorded once, never blessed (nw#226)."""

from __future__ import annotations

import nw
from lacing.digest import VALUE_DIGEST_SCHEME, VALUE_DIGEST_SCHEMES
from nw.bodies import VERIFYING_TRACE_TIER
from tests.test_freshness import (  # noqa: F401 — derived_field_schema is a fixture
    _as_recorded_under,
    _derived,
    _ids,
    _parent_with_derived_field,
    _rewrite_in_place,
    derived_field_schema,
)

OLD = VALUE_DIGEST_SCHEMES[0]


def _scheme_of_trace_for(proj, ann_id) -> str:
    (trace,) = [
        t for t in nw.annotations_at_tier(proj.root, VERIFYING_TRACE_TIER)
        if t.body.get("for_annotation_id") == str(ann_id)
    ]
    return trace.body["digest_scheme"]


def test_a_fresh_old_scheme_trace_moves_and_a_later_fill_no_longer_stales(
    tmp_path, derived_field_schema
):
    """The reelee#799 case: under v1 a fill of a Derived field reads as an
    upstream change; after the upgrade it does not."""
    proj = nw.Project.init(tmp_path / "p")
    parent = _parent_with_derived_field(proj)
    child = _derived(proj, (parent.id,), body={"url": "x"})
    _as_recorded_under(proj, child, OLD)
    assert nw.all_stale(proj.root) == []

    assert nw.upgrade_superseded_traces(proj) == 1
    assert _scheme_of_trace_for(proj, child.id) == VALUE_DIGEST_SCHEME
    assert nw.all_stale(proj.root) == []  # still fresh

    _rewrite_in_place(proj, parent, body={"artifact_id": "a", "asset_id": "2"})  # the fill
    assert nw.all_stale(proj.root) == []


def test_an_already_stale_trace_is_left_alone(tmp_path, derived_field_schema):
    proj = nw.Project.init(tmp_path / "p")
    parent = _parent_with_derived_field(proj)
    child = _derived(proj, (parent.id,), body={"url": "x"})
    _as_recorded_under(proj, child, OLD)
    _rewrite_in_place(proj, parent, body={"artifact_id": "CHANGED", "asset_id": "1"})
    assert _ids(nw.all_stale(proj.root)) == {child.id}

    assert nw.upgrade_superseded_traces(proj, marker=None) == 0
    assert _scheme_of_trace_for(proj, child.id) == OLD
    assert _ids(nw.all_stale(proj.root)) == {child.id}  # never blessed


def test_it_runs_once_per_project_under_its_marker(tmp_path, derived_field_schema):
    proj = nw.Project.init(tmp_path / "p")
    parent = _parent_with_derived_field(proj)
    child = _derived(proj, (parent.id,), body={"url": "x"})
    _as_recorded_under(proj, child, OLD)
    assert nw.upgrade_superseded_traces(proj) == 1
    _as_recorded_under(proj, child, OLD)  # as if an old process wrote again
    assert nw.upgrade_superseded_traces(proj) == 0  # the marker holds
    assert nw.upgrade_superseded_traces(proj, marker=None) == 1  # explicit re-run


def test_current_traces_are_untouched(tmp_path, derived_field_schema):
    proj = nw.Project.init(tmp_path / "p")
    parent = _parent_with_derived_field(proj)
    _derived(proj, (parent.id,), body={"url": "x"})
    assert nw.upgrade_superseded_traces(proj, marker=None) == 0


def test_a_stale_grandparent_keeps_the_child_stale_after_the_upgrade(
    tmp_path, derived_field_schema
):
    """Upstream-stale recursion is untouched: G changed, so P is stale on v1
    and stays so; C's own entries vouch and move, yet C still reads stale."""
    proj = nw.Project.init(tmp_path / "p")
    grand = _parent_with_derived_field(proj)
    parent = _derived(proj, (grand.id,), body={"url": "p"})
    child = _derived(proj, (parent.id,), body={"url": "c"})
    _as_recorded_under(proj, parent, OLD)
    _as_recorded_under(proj, child, OLD)
    _rewrite_in_place(proj, grand, body={"artifact_id": "CHANGED", "asset_id": "1"})
    assert _ids(nw.all_stale(proj.root)) == {parent.id, child.id}

    nw.upgrade_superseded_traces(proj, marker=None)
    assert _scheme_of_trace_for(proj, parent.id) == OLD  # stale: left alone
    assert _ids(nw.all_stale(proj.root)) == {parent.id, child.id}  # nobody blessed


def test_one_unprocessable_trace_does_not_stop_the_others(
    tmp_path, derived_field_schema, monkeypatch
):
    """A row that raises is left as it is; the rest still move and the marker
    is written, so the scan is not repeated on every call."""
    import nw.rewrite as rewrite

    proj = nw.Project.init(tmp_path / "p")
    p1 = _parent_with_derived_field(proj)
    p2 = _parent_with_derived_field(proj)
    c1 = _derived(proj, (p1.id,), body={"url": "1"})
    c2 = _derived(proj, (p2.id,), body={"url": "2"})
    _as_recorded_under(proj, c1, OLD)
    _as_recorded_under(proj, c2, OLD)

    real = rewrite.upstream_entry

    def breaks_on_p1(parent, *, scheme):
        if parent.id == p1.id:
            raise TypeError("a parent body outside the JSON contract")
        return real(parent, scheme=scheme)

    monkeypatch.setattr(rewrite, "upstream_entry", breaks_on_p1)
    assert nw.upgrade_superseded_traces(proj) == 1
    assert _scheme_of_trace_for(proj, c1.id) == OLD
    assert _scheme_of_trace_for(proj, c2.id) == VALUE_DIGEST_SCHEME
    assert nw.is_rewritten(proj, rewrite.TRACE_UPGRADE_MARKER)
