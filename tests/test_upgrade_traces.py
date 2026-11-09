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
