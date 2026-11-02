"""One freshness walk for a whole fan-out: :func:`nw.freshness_pass` (nw#209).

With ``reuse_fresh_outputs``, ``BaseTransform.execute`` reads the output tier
and walks freshness once per call, and ``fan_out_execute`` calls it once per
unit — so a K-unit re-run paid K tier reads and K walks. A pass holds them
across lookups until nw's own write paths drop them.

What these pin, through the real seams (falaw with a stubbed fal, the graph,
the freshness walk): one walk per fan-out re-run; a write inside the pass
makes the next lookup walk again (so a parent rewritten mid-pass reads
stale); nested passes share; no pass is the old behaviour; two projects never
share; a pass costs nothing to a Transform that does not reuse.
"""

from __future__ import annotations

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
