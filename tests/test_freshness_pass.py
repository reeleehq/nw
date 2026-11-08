"""One freshness walk for a whole fan-out: :func:`nw.freshness_pass` (nw#209).

With ``reuse_fresh_outputs``, ``BaseTransform.execute`` reads the output tier
and walks freshness once per call, and ``fan_out_execute`` calls it once per
unit — so a K-unit re-run paid K tier reads and K walks. A pass holds them
across lookups until nw's own write paths drop them.

What these pin, through the real seams (falaw with a stubbed fal, the graph,
the freshness walk): one walk per fan-out re-run; a write inside the pass
makes the next lookup walk again (so a parent rewritten mid-pass reads
stale) — from this thread or another, and through each of nw's write paths
(graph writes, ``remove_annotations_with_traces``, ``rewrite_values``);
nested passes share; no pass is the old behaviour; two projects never share;
a pass costs nothing to a Transform that does not reuse.
"""

from __future__ import annotations

import threading

import pytest

import nw
import nw.freshness as freshness
from nw.bodies import SectionBodyV1
from nw.transforms import BaseTransform
from nw.transforms.fanout import (
    FanOutPlan,
    FanOutUnit,
    WorkItem,
    fan_out_execute,
    work_item_instance_id,
)
from tests.test_fresh_equivalents import (  # noqa: F401 — `fal` is a fixture
    _Reusing,
    _count_walks,
    _iv,
    _nodes,
    _plan,
    _project,
    _skeleton,
    fal,
)


class _FanReusing(_Reusing):
    name = "x_to_y.test.fan_reusing"


class _FanPlain(BaseTransform):
    name = "x_to_y.test.fan_plain"


def _fan_out(transform, proj, shots) -> FanOutPlan:
    """One unit per shot, each an ordinary one-call plan."""
    units = []
    for i, shot in enumerate(shots):
        item = WorkItem(mapping_key=f"shot/{i}")
        units.append(
            FanOutUnit(
                item=item,
                instance_id=work_item_instance_id(transform.name, item.mapping_key),
                plan=_plan(),
                skeleton=(_skeleton(proj, (shot,), shot_id=f"s{i}"),),
            )
        )
    return FanOutPlan(transform_name=transform.name, units=tuple(units))


def _count_tier_reads(monkeypatch) -> list:
    calls: list = []
    real = freshness.annotations_at_tier

    def counting(*args, **kwargs):
        calls.append(args[1:])
        return real(*args, **kwargs)

    monkeypatch.setattr(freshness, "annotations_at_tier", counting)
    return calls


def _ids(fan_out_result) -> list:
    return [a.id for item in fan_out_result.items for a in item.result.annotations]


def test_a_fan_out_rerun_walks_once_not_per_unit(tmp_path, fal, monkeypatch):
    """Fails if ``fan_out_execute`` opens no pass, or if a reused unit's
    record-settling write drops it: each of the K units would walk the whole
    graph again (and re-read the tier), the cost nw#209 names."""
    proj, shots = _project(tmp_path, sections=("a", "b", "c"))
    t = _FanReusing()
    first = fan_out_execute(t, proj, _fan_out(t, proj, shots))

    walks = _count_walks(monkeypatch)
    reads = _count_tier_reads(monkeypatch)
    second = fan_out_execute(t, proj, _fan_out(t, proj, shots))

    assert len(walks) == 1
    assert len(reads) == 1
    assert _ids(second) == _ids(first)
    assert len(_nodes(proj)) == 3


def test_a_fan_out_record_says_which_units_outputs_were_reused(tmp_path, fal):
    """nw#215: each unit's ``reused_ids`` reaches the run record, so a reader
    counting what a run produced does not count reused rows as written."""
    proj, shots = _project(tmp_path, sections=("a", "b"))
    t = _FanReusing()
    first = fan_out_execute(t, proj, _fan_out(t, proj, shots)).to_record()
    assert all(row["reused_ids"] == [] for row in first["items"])

    second = fan_out_execute(t, proj, _fan_out(t, proj, shots)).to_record()
    for row in second["items"]:
        assert row["annotation_ids"] and row["reused_ids"] == sorted(row["annotation_ids"])


# --- the public read of the held walk, and the walk counter (nw#222) ---------


def test_fresh_ids_shares_the_passs_walk_with_fresh_equivalents(tmp_path, fal):
    """A host choosing among candidates inside a pass pays no walk of its own:
    ``fresh_ids`` answers from the walk the reuse lookups took (or takes it
    for them), so a whole re-run is one walk."""
    proj, shots = _project(tmp_path, sections=("a", "b"))
    t = _FanReusing()
    first = fan_out_execute(t, proj, _fan_out(t, proj, shots))

    before = nw.freshness.walk_count()
    with nw.freshness_pass():
        fresh = nw.fresh_ids(proj)
        fan_out_execute(t, proj, _fan_out(t, proj, shots))  # reuses: no write
        assert nw.fresh_ids(proj) is fresh
    assert nw.freshness.walk_count() - before == 1
    assert set(_ids(first)) <= fresh
    assert isinstance(fresh, frozenset)


def test_fresh_ids_outside_a_pass_walks_every_call(tmp_path, fal):
    proj, (shot,) = _project(tmp_path)
    out = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))
    before = nw.freshness.walk_count()
    assert out.annotations[0].id in nw.fresh_ids(proj)
    assert out.annotations[0].id in nw.fresh_ids(proj)
    assert nw.freshness.walk_count() - before == 2


def test_fresh_ids_holds_parentless_rows_and_every_walk_is_counted(tmp_path, fal):
    proj, (shot,) = _project(tmp_path)
    _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))
    assert shot in nw.fresh_ids(proj)  # an authored, parentless row
    before = nw.freshness.walk_count()
    nw.stale_verdicts_all(proj)
    assert nw.freshness.walk_count() - before == 1


def test_a_write_drops_the_fresh_ids_the_pass_held(tmp_path, fal):
    """Fails if ``fresh_ids`` keeps answering from a walk taken before a write:
    a parent edited mid-pass makes its derived node stale, and the held set
    must not still call it fresh."""
    proj, (shot,) = _project(tmp_path)
    out = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))
    with nw.freshness_pass():
        assert out.annotations[0].id in nw.fresh_ids(proj)
        proj.graph.upsert_section(
            SectionBodyV1(section_id="s", label="edited"), interval=_iv(0, 4)
        )
        assert out.annotations[0].id not in nw.fresh_ids(proj)


def test_a_write_inside_the_pass_makes_the_next_lookup_walk_again(tmp_path, fal):
    """Fails if a graph write does not drop the held walk: a parent rewritten
    in place mid-pass keeps its id, the held walk still says the old output is
    fresh, and the next lookup hands back a node derived from a value that no
    longer exists (braidio#51, now across a whole pass)."""
    proj, (shot,) = _project(tmp_path)
    first = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))

    with nw.freshness_pass():
        again = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))
        assert again.annotations[0].id == first.annotations[0].id  # walk held

        proj.graph.upsert_section(
            SectionBodyV1(section_id="s", label="edited"), interval=_iv(0, 4)
        )
        after = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))

    assert after.annotations[0].id != first.annotations[0].id
    assert len(_nodes(proj)) == 2


def test_nested_passes_share_the_outer_one(tmp_path, fal, monkeypatch):
    """Fails if an inner pass replaces the outer one's state, or clears it on
    exit: a fan-out run inside a caller's pass (braidio's weave) would walk
    again for every nesting."""
    proj, (shot,) = _project(tmp_path)
    _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))
    walks = _count_walks(monkeypatch)

    with nw.freshness_pass():
        _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))
        with nw.freshness_pass():
            _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))
        _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))

    assert len(walks) == 1


def test_without_a_pass_every_lookup_walks(tmp_path, fal, monkeypatch):
    """Fails if held state outlives its pass (or exists without one): a
    lookup outside any pass would answer from a walk taken before writes it
    never heard of."""
    proj, (shot,) = _project(tmp_path)
    _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))
    with nw.freshness_pass():
        _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))

    walks = _count_walks(monkeypatch)
    for _ in range(2):
        _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))

    assert len(walks) == 2
    assert len(_nodes(proj)) == 1


def test_two_projects_in_one_pass_do_not_share(tmp_path, fal, monkeypatch):
    """Fails if held state is not keyed by project: the second project would
    be answered from the first one's walk, where its own node is unknown, and
    write a duplicate (or, worse, be handed the other project's node)."""
    proj_a, (shot_a,) = _project(tmp_path / "a")
    proj_b, (shot_b,) = _project(tmp_path / "b")
    first_a = _Reusing().execute(proj_a, _plan(), (_skeleton(proj_a, (shot_a,)),))
    first_b = _Reusing().execute(proj_b, _plan(), (_skeleton(proj_b, (shot_b,)),))
    walks = _count_walks(monkeypatch)

    with nw.freshness_pass():
        a = _Reusing().execute(proj_a, _plan(), (_skeleton(proj_a, (shot_a,)),))
        b = _Reusing().execute(proj_b, _plan(), (_skeleton(proj_b, (shot_b,)),))

    assert len(walks) == 2
    assert a.annotations[0].id == first_a.annotations[0].id
    assert b.annotations[0].id == first_b.annotations[0].id
    assert len(_nodes(proj_a)) == len(_nodes(proj_b)) == 1


@pytest.mark.parametrize("rerun", [False, True], ids=["first-run", "re-run"])
def test_a_pass_costs_nothing_to_a_transform_that_does_not_reuse(
    tmp_path, fal, monkeypatch, rerun
):
    """Fails if the pass starts any read or walk eagerly: every fan-out opens
    one, and a Transform that never looks anything up would pay for it."""
    proj, shots = _project(tmp_path, sections=("a", "b"))
    t = _FanPlain()
    if rerun:
        fan_out_execute(t, proj, _fan_out(t, proj, shots))
    walks = _count_walks(monkeypatch)
    reads = _count_tier_reads(monkeypatch)

    fan_out_execute(t, proj, _fan_out(t, proj, shots))

    assert walks == [] and reads == []
    assert len(_nodes(proj)) == (4 if rerun else 2)


def _edit_parent(proj) -> None:
    proj.graph.upsert_section(
        SectionBodyV1(section_id="s", label="edited"), interval=_iv(0, 4)
    )


def test_a_write_from_another_thread_drops_the_held_walk(tmp_path, fal):
    """Fails if invalidation only reaches the writer's own context: a request
    thread editing a shot while a fan-out runs on a worker (au's
    ThreadBackend copies no ContextVars) would leave the fan-out answering
    from a walk that still calls the edited shot's old render fresh."""
    proj, (shot,) = _project(tmp_path)
    first = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))

    with nw.freshness_pass():
        again = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))
        assert again.annotations[0].id == first.annotations[0].id  # walk held
        editor = threading.Thread(target=_edit_parent, args=(proj,))
        editor.start()
        editor.join()
        after = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))

    assert after.annotations[0].id != first.annotations[0].id
    assert len(_nodes(proj)) == 2


def test_remove_with_traces_mid_pass_drops_the_held_walk(tmp_path, fal):
    """Fails if ``remove_annotations_with_traces`` does not drop the held
    state: a node deleted through a raw store mid-pass (a storyboard
    re-save's path) would still be in the held tier and walk, and be handed
    back as the output — an id no longer in the graph."""
    from nw.graph import remove_annotations_with_traces

    proj, (shot,) = _project(tmp_path)
    first = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))
    gone = first.annotations[0].id

    with nw.freshness_pass():
        _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))
        store = proj.graph.storage.open_graph()
        try:
            remove_annotations_with_traces(store, {gone})
        finally:
            store.close()
        after = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))

    assert after.annotations[0].id != gone
    assert [n.id for n in _nodes(proj)] == [after.annotations[0].id]


def test_rewrite_values_mid_pass_drops_the_held_tier(tmp_path, fal):
    """Fails if ``rewrite_values`` does not drop the held state: the held
    tier still carries the output's old body, so a lookup for that old value
    matches it and hands back a node whose stored body no longer says that."""
    proj, (shot,) = _project(tmp_path)
    first = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))

    def rename(body):
        if body.get("strategy") == "test":
            return {**body, "strategy": "renamed"}
        return body

    with nw.freshness_pass():
        _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))
        assert nw.rewrite_values(proj, rename) == 1
        after = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))

    assert after.annotations[0].id != first.annotations[0].id
    stored = {n.id: n.body["strategy"] for n in _nodes(proj)}
    assert stored == {
        first.annotations[0].id: "renamed",
        after.annotations[0].id: "test",
    }
