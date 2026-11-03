"""A re-run whose output is already fresh reuses the node (nw#203).

``BaseTransform.execute`` used to write a new output node on every run, cache
hits included, so two identical runs of a Transform left two equivalent nodes.
A Transform that declares ``reuse_fresh_outputs = True`` now has it ask
:func:`nw.freshness.fresh_equivalents` first and return the existing node in
place of a duplicate. The declaration is opt-in, so the default (every run
writes) is pinned here too.

What these pin, each through the real seams (``falaw.execute_plan`` with the
fal response stubbed and assets served from memory by the conftest's
``fake_assets``, ``BaseTransform.execute``, ``ProjectGraph.add_annotation``):

* an identical re-run writes nothing and returns the first node;
* a parent rewritten **in place** (same id, new value) is not mistaken for
  unchanged — the old node is stale, so the re-run writes a new one;
* a different body (a new artifact) is written as before;
* a node written before nw#55 (no asset refs in ``was_derived_from``) still
  matches;
* several skeletons of one ``execute`` share one freshness walk, and a run
  with no candidates walks none;
* without the declaration, every run still writes a new node;
* a different producer (another Transform, or a bumped ``impl_version``), a
  different reference, or a node whose verifying trace is gone is never
  reused;
* reuse works on a ``MappingStorage``-backed project, and a duck-typed graph
  lacking either reuse method keeps the old behaviour;
* a reused success still retires the unproduced-output record it settles
  (nw#44).
"""

from __future__ import annotations

import sys
import types
from uuid import UUID, uuid4

import pytest

import nw
import nw.freshness as freshness
from lacing import (
    Annotation,
    MediaRef,
    Provenance,
    RationalTime,
    TimeInterval,
    hash_bytes,
)
from nw.bodies import SectionBodyV1
from nw.transforms import BaseTransform


IMG_A = b"\x89PNG-pretend-image-A" * 4
IMG_B = b"\x89PNG-pretend-image-B" * 4

TIER = "render-result"
RENDER_SCHEMA = "annot://schema/render-result/v1"
AN_ASSET_ID = "ab" * 32  # a 64-hex artifact parent, as nw#55 writes them


class _FakeFal:
    """Returns ``next_image_url`` for every call; counts the calls it served."""

    def __init__(self) -> None:
        self.calls: list[dict] = []
        self.next_image_url = "http://cdn/img-1.png"

    def subscribe(self, application, *, arguments, with_logs, on_queue_update):
        self.calls.append({"application": application, "arguments": dict(arguments)})
        return {"images": [{"url": self.next_image_url, "content_type": "image/png"}]}


@pytest.fixture
def fal(monkeypatch, fake_assets):
    stub = _FakeFal()
    monkeypatch.setitem(
        sys.modules,
        "fal_client",
        types.SimpleNamespace(
            InProgress=type("IP", (), {"__init__": lambda s, logs: None}),
            subscribe=stub.subscribe,
        ),
    )
    fake_assets.serve(stub.next_image_url, IMG_A)
    return stub


class _Reusing(BaseTransform):
    """A plain BaseTransform that opts in to reuse (nw#203)."""

    reuse_fresh_outputs = True


def _iv(a: float, b: float) -> TimeInterval:
    return TimeInterval.from_seconds(a, b)


def _plan(n: int = 1):
    from falaw import CallPlan, Plan

    return Plan(
        calls=tuple(
            CallPlan(
                tool="generate_image",
                application="fal-ai/flux/dev",
                arguments={"prompt": f"a tiger #{i}"},
                output_kind="image",
                estimated_cost_usd=0.02,
            )
            for i in range(n)
        )
    )


def _skeleton(
    proj,
    parents,
    *,
    shot_id: str = "s01",
    generated_by: str = "transform:test@1",
    interval: tuple[float, float] = (0, 0),
) -> Annotation:
    """A plan-time render skeleton (``artifact_id`` empty until execute),
    shaped the way ``derive_provenance`` shapes one."""
    return Annotation(
        id=uuid4(),
        tier=TIER,
        reference=MediaRef(asset_id=proj.graph.asset_id, interval=_iv(*interval)),
        body={"shot_id": shot_id, "strategy": "test", "artifact_id": None},
        body_schema_uri=RENDER_SCHEMA,
        provenance=Provenance(
            was_generated_by=generated_by,
            was_attributed_to="agent:test",
            was_derived_from=list(parents),
            generated_at_time=RationalTime.now(),
            activity="derive",
        ),
    )


def _project(tmp_path, *, sections=("s",)):
    proj = nw.Project.init(tmp_path / "p")
    ids = [
        proj.graph.upsert_section(
            SectionBodyV1(section_id=s, label="seed"), interval=_iv(0, 4)
        )
        for s in sections
    ]
    return proj, ids


def _nodes(proj) -> list[Annotation]:
    return nw.annotations_at_tier(proj.root, TIER)


# --- reuse -------------------------------------------------------------------


def test_an_identical_rerun_writes_nothing_and_returns_the_first_node(tmp_path, fal):
    """Fails if execute writes a node on a cache hit — the nw#203 defect: two
    identical runs leaving two equivalent nodes in the graph."""
    proj, (shot,) = _project(tmp_path)

    first = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))
    second = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))

    assert len(fal.calls) == 1  # the premise: the re-run was a cache hit
    assert [n.id for n in _nodes(proj)] == [first.annotations[0].id]
    assert second.annotations[0].id == first.annotations[0].id
    assert second.annotations[0].body == first.annotations[0].body
    assert second.is_complete


def test_without_the_declaration_every_run_writes_a_new_node(tmp_path, fal):
    """Fails if reuse is on by default: a host that drops or re-ids the rows
    ``execute`` returns (reelee's regen adoption) would then delete a live
    node it never wrote. Pins the historical behaviour of an undeclared
    Transform."""
    assert BaseTransform.reuse_fresh_outputs is False
    proj, (shot,) = _project(tmp_path)
    skels = [_skeleton(proj, (shot,)) for _ in range(2)]

    first = BaseTransform().execute(proj, _plan(), (skels[0],))
    second = BaseTransform().execute(proj, _plan(), (skels[1],))

    assert len(fal.calls) == 1  # a cache hit, yet written again
    assert [first.annotations[0].id, second.annotations[0].id] == [s.id for s in skels]
    assert len(_nodes(proj)) == 2


def test_a_parent_rewritten_in_place_is_not_mistaken_for_unchanged(tmp_path, fal):
    """Fails if reuse trusts equal parent *ids*: a parent rewritten in place
    keeps its id (braidio#51), so the old node has "the same parents" while
    being derived from a value that no longer exists. Only the freshness walk
    tells them apart."""
    proj, (shot,) = _project(tmp_path)
    first = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))

    same_id = proj.graph.upsert_section(
        SectionBodyV1(section_id="s", label="edited"), interval=_iv(0, 4)
    )
    assert same_id == shot
    assert first.annotations[0].id in {a.id for a in nw.all_stale(proj.root)}

    second = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))

    assert len(fal.calls) == 1  # still a cache hit: the body is identical
    assert second.annotations[0].id != first.annotations[0].id
    assert len(_nodes(proj)) == 2
    assert second.annotations[0].id not in {a.id for a in nw.all_stale(proj.root)}


def test_a_different_body_is_written_as_a_new_node(tmp_path, fal, fake_assets):
    """Fails if reuse compares less than the whole body: a genuinely new render
    (cache bypassed, new bytes → new ``artifact_id``) must not be swallowed by
    the old node."""
    proj, (shot,) = _project(tmp_path)
    first = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))

    fal.next_image_url = "http://cdn/img-2.png"
    fake_assets.serve(fal.next_image_url, IMG_B)
    second = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),), force=True)

    assert len(fal.calls) == 2
    assert second.annotations[0].body["artifact_id"] == hash_bytes(IMG_B)
    assert second.annotations[0].id != first.annotations[0].id
    assert len(_nodes(proj)) == 2


def _pre_55_node(proj, shot: UUID) -> Annotation:
    """A render written before nw#55: annotation parents only, no asset refs,
    with the body a run serving ``IMG_A`` completes to."""
    old = _skeleton(proj, (shot,))
    old = old.model_copy(
        update={"body": {**old.body, "artifact_id": hash_bytes(IMG_A)}}
    )
    proj.graph.add_annotation(old)
    return old


def test_a_node_written_before_asset_refs_still_matches(tmp_path, fal):
    """Fails if reuse compares the whole ``was_derived_from``: since nw#55 a
    re-plan adds artifact ids to it, so no node written before would ever
    match and one re-plan would duplicate every such node."""
    proj, (shot,) = _project(tmp_path)
    old = _pre_55_node(proj, shot)

    result = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot, AN_ASSET_ID)),))

    assert result.annotations[0].id == old.id
    assert [n.id for n in _nodes(proj)] == [old.id]


# --- cost ----------------------------------------------------------------------


def _count_walks(monkeypatch) -> list:
    calls: list = []
    real = freshness._verdicts_for

    def counting(*args, **kwargs):
        calls.append(kwargs.get("scope"))
        return real(*args, **kwargs)

    monkeypatch.setattr(freshness, "_verdicts_for", counting)
    return calls


def test_several_skeletons_share_one_freshness_walk(tmp_path, fal, monkeypatch):
    """Fails if the freshness walk runs per skeleton: a fan-out of N outputs
    would walk the whole graph N times (the cost braidio#171 batched away)."""
    proj, shots = _project(tmp_path, sections=("a", "b", "c"))

    def skeletons():
        return tuple(
            _skeleton(proj, (s,), shot_id=f"s{i}") for i, s in enumerate(shots)
        )

    walks = _count_walks(monkeypatch)
    first = _Reusing().execute(proj, _plan(3), skeletons())
    assert walks == []  # nothing to reuse yet, so nothing is walked

    second = _Reusing().execute(proj, _plan(3), skeletons())
    assert len(walks) == 1
    assert [a.id for a in second.annotations] == [a.id for a in first.annotations]
    assert len(_nodes(proj)) == 3


# --- unproduced-output records (nw#44) ----------------------------------------


def test_a_reused_success_retires_its_unproduced_output_record(tmp_path, fal):
    """Fails if a reused success skips the retirement ``add_annotation`` does:
    the record of an earlier failed attempt would read as a live blocker
    after reload, although the output now exists."""
    proj, (shot,) = _project(tmp_path)
    _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))

    retry = _skeleton(proj, (shot,))
    proj.graph.add_unproduced_output(
        retry,
        transform_name="test",
        status="failed",
        reason="rate limited",
        instance_id="unit-1",
        call_index=0,
    )
    assert len(proj.graph.unproduced_outputs()) == 1

    _Reusing().execute(proj, _plan(), (retry,), unit_instance_id="unit-1")

    assert len(_nodes(proj)) == 1
    assert nw.ProjectGraph(proj.root).unproduced_outputs() == []


def test_retirement_reads_this_runs_upstream_not_the_reused_nodes(tmp_path, fal):
    """Fails if the record is retired by the *reused* node's identity: without
    an ``instance_id`` the key includes ``upstream``, and a pre-nw#55 node
    lacks the asset ids this run's skeleton (and its record) carry."""
    proj, (shot,) = _project(tmp_path)
    old = _pre_55_node(proj, shot)

    retry = _skeleton(proj, (shot, AN_ASSET_ID))
    proj.graph.add_unproduced_output(
        retry, transform_name="test", status="failed", reason="boom", call_index=0
    )

    result = _Reusing().execute(proj, _plan(), (retry,))

    assert result.annotations[0].id == old.id
    assert nw.ProjectGraph(proj.root).unproduced_outputs() == []


# --- what is never reused -------------------------------------------------------


@pytest.mark.parametrize(
    "producer", ["transform:other@1", "transform:test@2"], ids=["other", "bumped"]
)
def test_another_producer_is_not_reused(tmp_path, fal, producer):
    """Fails if the key leaves out ``was_generated_by``: another Transform's
    node would be handed back as this one's output, and after an
    ``impl_version`` bump the old version's node would keep coming back —
    freshness does not see a changed Transform, so only the key can."""
    proj, (shot,) = _project(tmp_path)
    first = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))

    second = _Reusing().execute(
        proj, _plan(), (_skeleton(proj, (shot,), generated_by=producer),)
    )

    assert second.annotations[0].id != first.annotations[0].id
    assert len(_nodes(proj)) == 2


def test_a_different_reference_is_not_reused(tmp_path, fal):
    """Fails if the key leaves out ``reference``: an output at another place
    (interval) would be answered with a node that sits somewhere else."""
    proj, (shot,) = _project(tmp_path)
    first = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))

    second = _Reusing().execute(
        proj, _plan(), (_skeleton(proj, (shot,), interval=(1, 2)),)
    )

    assert second.annotations[0].id != first.annotations[0].id
    assert len(_nodes(proj)) == 2


def test_a_host_can_leave_the_reference_out_of_the_identity(tmp_path):
    """nw#218: a host whose references are per-node tokens (braidio's node refs
    carry a fresh uuid) opts out with ``reference_of``; the default still
    refuses a node at another place."""
    proj, (shot,) = _project(tmp_path)
    stored = _skeleton(proj, (shot,), interval=(1, 2))
    proj.graph.add_annotation(stored)
    elsewhere = _skeleton(proj, (shot,), interval=(3, 4))

    assert nw.fresh_equivalents(proj, [elsewhere]) == (None,)
    (found,) = nw.fresh_equivalents(proj, [elsewhere], reference_of=lambda a: None)
    assert found is not None and found.id == stored.id


def test_a_node_whose_trace_is_gone_is_not_reused(tmp_path, fal):
    """Fails if reuse trusts a node it cannot verify: with its verifying trace
    gone it is unverifiable, and unverifiable means stale (nw.freshness)."""
    from nw.bodies import VERIFYING_TRACE_TIER

    proj, (shot,) = _project(tmp_path)
    first = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))
    target = str(first.annotations[0].id)
    with nw.open_project_stores(proj.root) as stores:
        for store in stores:
            for t in list(store.by_tier(VERIFYING_TRACE_TIER)):
                if t.body.get("for_annotation_id") == target:
                    store.remove(t.id)

    second = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))

    assert second.annotations[0].id != first.annotations[0].id
    assert len(_nodes(proj)) == 2


# --- where it runs ----------------------------------------------------------------


def test_reuse_works_on_a_mapping_storage_project(tmp_path, fal):
    """Fails if the rule opens the graph by path instead of through the
    project's storage: a ``MappingStorage`` project keeps its graph in the
    caller's mapping, with no ``project.annot.sqlite`` to find."""
    proj = nw.Project.init(
        tmp_path,
        title="t",
        storage=nw.MappingStorage(root=tmp_path, graph={}, docs={}),
    )
    shot = proj.graph.upsert_section(
        SectionBodyV1(section_id="s", label="seed"), interval=_iv(0, 4)
    )

    first = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))
    second = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))

    assert second.annotations[0].id == first.annotations[0].id
    assert len(nw.annotations_at_tier(proj.storage, TIER)) == 1


def test_a_graph_lacking_a_reuse_method_keeps_the_old_behaviour(tmp_path, fal):
    """Fails if execute looks the two reuse methods up separately: a host
    graph offering ``fresh_equivalents`` but not ``settle_unproduced_outputs``
    would find an equivalent and then raise ``AttributeError``."""
    proj, (shot,) = _project(tmp_path)
    real = proj.graph

    class _HostGraph:  # finds equivalents, cannot settle records
        fresh_equivalents = staticmethod(real.fresh_equivalents)
        add_annotation = staticmethod(real.add_annotation)
        add_unproduced_output = staticmethod(real.add_unproduced_output)

    host = types.SimpleNamespace(root=proj.root, graph=_HostGraph())
    first = _Reusing().execute(host, _plan(), (_skeleton(proj, (shot,)),))
    second = _Reusing().execute(host, _plan(), (_skeleton(proj, (shot,)),))

    assert second.annotations[0].id != first.annotations[0].id
    assert len(_nodes(proj)) == 2


def test_a_failing_lookup_writes_every_output(tmp_path, fal, monkeypatch, caplog):
    """Fails if a raising reuse lookup propagates: the run's paid outputs would
    never be written. Reuse only saves a write, so a failed lookup writes."""
    proj, (shot,) = _project(tmp_path)
    first = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))

    def broken(*args, **kwargs):
        raise OSError("graph unreadable")

    monkeypatch.setattr(proj.graph, "fresh_equivalents", broken)
    second = _Reusing().execute(proj, _plan(), (_skeleton(proj, (shot,)),))

    assert second.annotations[0].id != first.annotations[0].id
    assert len(_nodes(proj)) == 2
    assert "fresh-output lookup failed" in caplog.text
