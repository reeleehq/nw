"""``nw.rewrite_values`` — change stored values without making dependents stale (nw#132)."""

from __future__ import annotations

import pytest

import nw
from nw import Project, rewrite_values
from nw.freshness import all_stale

from tests.test_freshness import _derived, _traces  # scaffolding shared with the freshness suite


def _rename(body):
    """Rename the ``style`` value ``old`` -> ``new`` wherever a dict stores it."""
    if isinstance(body, dict):
        return {
            k: ("new" if k == "style" and v == "old" else _rename(v))
            for k, v in body.items()
        }
    return body


@pytest.fixture
def proj(tmp_path):
    return Project.init(tmp_path / "p", title="Rewrite")


def _source(proj):
    return _derived(proj, [], body={"style": "old", "keep": 1})


def _bodies(proj):
    return {a.id: a.body for a in nw.iter_all_annotations(proj.root)}


def test_rewrite_changes_values_keeps_identity_and_moves_no_verdict(proj):
    src = _source(proj)
    child = _derived(proj, [src.id], body={"shot_id": "c"})
    before_traces = len(_traces(proj))
    assert all_stale(proj.root) == []

    assert rewrite_values(proj, _rename) == 1

    after = _bodies(proj)
    assert after[src.id] == {"style": "new", "keep": 1}
    assert after[child.id] == {"shot_id": "c"}
    stored = {a.id: a for a in nw.iter_all_annotations(proj.root)}
    assert stored[src.id].provenance == src.provenance  # identity/provenance kept
    assert len(_traces(proj)) == before_traces
    assert all_stale(proj.root) == []  # the point: nothing reads upstream-changed


def test_a_bare_rewrite_would_make_dependents_stale(proj):
    """Control: without the re-stamp, the same edit does stale the child."""
    src = _source(proj)
    child = _derived(proj, [src.id], body={"shot_id": "c"})
    with nw.open_project_stores(proj.root) as stores:
        for store in stores:
            for ann in list(store.all()):
                if ann.id == src.id:
                    store.update(ann.model_copy(update={"body": _rename(ann.body)}))
    assert [a.id for a in all_stale(proj.root)] == [child.id]


def test_already_stale_stays_stale(proj):
    src = _source(proj)
    child = _derived(proj, [src.id], body={"shot_id": "c"})
    with nw.open_project_stores(proj.root) as stores:  # make the child stale first
        for store in stores:
            for ann in list(store.all()):
                if ann.id == src.id:
                    store.update(ann.model_copy(update={"body": {"style": "old", "keep": 2}}))
    assert [a.id for a in all_stale(proj.root)] == [child.id]
    rewrite_values(proj, _rename)
    assert [a.id for a in all_stale(proj.root)] == [child.id]


def test_marker_makes_it_once_and_is_success_only(proj):
    _source(proj)
    calls = []

    def boom(body):
        calls.append(1)
        raise RuntimeError("fail")

    with pytest.raises(RuntimeError):
        rewrite_values(proj, boom, marker="m")
    assert not nw.is_rewritten(proj, "m")  # failure is not recorded as done

    assert rewrite_values(proj, _rename, marker="m") == 1
    assert nw.is_rewritten(proj, "m")
    assert rewrite_values(proj, _rename, marker="m") == 0  # marker short-circuits
    assert rewrite_values(proj, _rename) == 0  # nothing left to change anyway


def test_accepts_a_path_and_a_storage(proj):
    _source(proj)
    assert rewrite_values(str(proj.root), _rename) == 1
    assert rewrite_values(nw.as_project_storage(proj.root), _rename) == 0
