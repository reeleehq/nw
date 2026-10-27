"""``nw.rewrite_values`` — change stored values without making dependents stale (nw#132)."""

from __future__ import annotations

from pathlib import Path

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


def test_accepts_a_path_a_storage_and_a_project(proj):
    _source(proj)
    assert rewrite_values(str(proj.root), _rename) == 1
    _source_again = _derived(proj, [], body={"style": "old"})
    assert rewrite_values(nw.as_project_storage(proj.root), _rename) == 1
    _derived(proj, [], body={"style": "old", "n": 3})
    assert rewrite_values(proj, _rename) == 1


def test_verifying_traces_are_not_handed_to_fn(proj):
    src = _source(proj)
    _derived(proj, [src.id], body={"shot_id": "c"})
    seen = []

    def add_a_field(body):  # would corrupt a trace body if it saw one
        seen.append(body)
        return {**body, "v": 2}

    assert rewrite_values(proj, add_a_field) == 2  # the two value rows, no trace
    assert [t.body for t in _traces(proj)] != []
    assert all("upstream" not in b for b in seen)
    assert all_stale(proj.root) == []


def test_fn_may_mutate_in_place(proj):
    src = _source(proj)
    child = _derived(proj, [src.id], body={"shot_id": "c"})

    def mutate(body):
        if body.get("style") == "old":
            body["style"] = "new"
        return body

    assert rewrite_values(proj, mutate) == 1
    assert _bodies(proj)[src.id]["style"] == "new"
    assert all_stale(proj.root) == []


def test_where_selects_rows_by_schema(proj):
    src = _source(proj)
    assert rewrite_values(proj, _rename, where=lambda a: False) == 0
    assert _bodies(proj)[src.id]["style"] == "old"


@pytest.mark.parametrize("bad", ["../x", "a/b", "", ".hidden", "a b"])
def test_marker_must_be_a_slug_and_is_checked_before_any_work(proj, bad):
    src = _source(proj)
    with pytest.raises(ValueError):
        rewrite_values(proj, _rename, marker=bad)
    assert _bodies(proj)[src.id]["style"] == "old"


def test_crash_between_passes_heals_on_retry(proj):
    src = _source(proj)
    _derived(proj, [src.id], body={"shot_id": "c"})
    calls = {"n": 0}

    def flaky(body):
        calls["n"] += 1
        if calls["n"] == 3:  # 2 planning calls, then die on the first body write
            raise RuntimeError("crash")
        return _rename(body)

    with pytest.raises(RuntimeError):
        rewrite_values(proj, flaky, marker="m")
    assert not nw.is_rewritten(proj, "m")
    assert rewrite_values(proj, _rename, marker="m") == 1
    assert all_stale(proj.root) == []
    assert _bodies(proj)[src.id]["style"] == "new"


def test_two_rewrites_in_sequence_keep_dependents_fresh(proj):
    src = _source(proj)
    _derived(proj, [src.id], body={"shot_id": "c"})
    rewrite_values(proj, _rename, marker="a")
    rewrite_values(proj, lambda b: {**b, "keep": 2} if "keep" in b else b, marker="b")
    assert all_stale(proj.root) == []


def test_mark_rewritten_skips_the_scan(proj):
    src = _source(proj)
    nw.mark_rewritten(proj, "m")
    assert rewrite_values(proj, _rename, marker="m") == 0
    assert _bodies(proj)[src.id]["style"] == "old"


def test_unmark_rewritten_makes_the_next_rewrite_scan_again(proj):
    src = _source(proj)
    nw.mark_rewritten(proj, "m")
    nw.unmark_rewritten(proj, "m")
    assert not nw.is_rewritten(proj, "m")
    nw.unmark_rewritten(proj, "m")  # idempotent: absent is not an error
    assert rewrite_values(proj, _rename, marker="m") == 1
    assert _bodies(proj)[src.id]["style"] == "new"
    assert nw.is_rewritten(proj, "m")


def test_unmark_rewritten_of_an_absent_marker_writes_nothing(tmp_path):
    bare = tmp_path / "not-a-project"
    nw.unmark_rewritten(bare, "m")
    assert not bare.exists()


def test_unmark_rewritten_clears_a_corrupt_marker(proj):
    from nw.rewrite import MARKER_PREFIX

    nw.mark_rewritten(proj, "m")
    marker_file = Path(proj.root) / f"{MARKER_PREFIX}m.json"
    marker_file.write_text("{not json")
    nw.unmark_rewritten(proj, "m")
    assert not marker_file.exists() and not nw.is_rewritten(proj, "m")


def test_unmark_rewritten_raises_when_the_delete_fails(proj, monkeypatch):
    """dol turns a failed delete into ``KeyError``; it must not read as "already gone"."""
    import os

    nw.mark_rewritten(proj, "m")

    def _refuse(path):
        raise PermissionError(f"read-only mount: {path}")

    monkeypatch.setattr(os, "remove", _refuse)  # json_docs' delete_func
    with pytest.raises(KeyError):  # a path: a storage built after the patch
        nw.unmark_rewritten(proj.root, "m")
    monkeypatch.undo()
    assert nw.is_rewritten(proj, "m")


def test_unmark_rewritten_checks_the_slug(proj):
    with pytest.raises(ValueError):
        nw.unmark_rewritten(proj, "../x")


def test_works_on_a_mapping_storage(tmp_path):
    from tests.test_storage import _mapping_storage

    storage = _mapping_storage(tmp_path)
    mproj = Project.init(tmp_path, title="t", storage=storage)
    src = _derived(mproj, [], body={"style": "old"})
    child = _derived(mproj, [src.id], body={"shot_id": "c"})
    assert rewrite_values(storage, _rename, marker="m") == 1
    assert nw.is_rewritten(storage, "m")
    assert {a.id: a.body for a in nw.iter_all_annotations(storage)}[src.id] == {"style": "new"}
    assert all_stale(storage) == []
    nw.unmark_rewritten(storage, "m")
    assert not nw.is_rewritten(storage, "m")
