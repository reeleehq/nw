"""Genre stages (reelee#458): declaration, graph-derived state, ask-time price."""

from __future__ import annotations

from uuid import uuid4

import pytest

import nw
from lacing import Annotation, MediaRef, Provenance, RationalTime, TimeInterval
from nw.bodies import SectionBodyV1
from nw.bodies.section import SECTION_BODY_SCHEMA_URI
from nw.stages import Stage, stage_overview, stage_prices, stage_states

SCHEMA = "annot://schema/render-result/v1"


def _genre(slug="stg_demo"):
    return nw.Genre(
        slug=slug,
        title="Demo",
        transform_names=("img.t", "clip.t"),
        stages=(
            Stage("idea", "The idea", free=True, body_schema_uris=(SECTION_BODY_SCHEMA_URI,)),
            Stage("images", "Make the pictures", transform_names=("img.t",)),
            Stage("clips", "Film the shots", transform_names=("clip.t",)),
            Stage("voice", "Record the narration"),
        ),
    )


def _produce(proj, transform, parents=()):
    ann = Annotation(
        id=uuid4(),
        tier="render-result",
        reference=MediaRef(
            asset_id=proj.graph.asset_id, interval=TimeInterval.from_seconds(0, 0)
        ),
        body={"shot_id": "s", "url": "x"},
        body_schema_uri=SCHEMA,
        provenance=Provenance(
            was_generated_by=f"transform:{transform}@1",
            was_attributed_to="agent:test",
            was_derived_from=list(parents),
            generated_at_time=RationalTime.now(),
            activity="derive",
        ),
    )
    proj.graph.add_annotation(ann)
    return ann


@pytest.fixture
def proj(tmp_path):
    return nw.Project.init(tmp_path / "p")


def _states(proj):
    return {s.stage.slug: s.state for s in stage_states(_genre().stages, proj)}


def test_declaration_is_validated():
    with pytest.raises(ValueError, match="unique"):
        nw.Genre(slug="d1", title="D", stages=(Stage("a", "A"), Stage("a", "B")))
    with pytest.raises(ValueError, match="not among"):
        nw.Genre(slug="d2", title="D", stages=(Stage("a", "A", transform_names=("nope",)),))
    with pytest.raises(ValueError):
        Stage("a", " ")
    assert nw.Genre(slug="d3", title="D").to_dict()["stages"] == []


def test_catalog_carries_plain_english_stages():
    d = _genre().to_dict()["stages"]
    assert [s["name"] for s in d][:2] == ["The idea", "Make the pictures"]


def test_state_is_derived_from_the_graph(proj):
    assert _states(proj) == {
        "idea": "not_started", "images": "not_started", "clips": "not_started",
        "voice": "unknown",  # names nothing the graph could show: not guessed
    }
    sec = proj.graph.upsert_section(
        SectionBodyV1(section_id="s", label="seed"),
        interval=TimeInterval.from_seconds(0, 4),
    )
    img = _produce(proj, "img.t", (sec,))
    st = _states(proj)
    assert st["idea"] == "done" and st["images"] == "done" and st["clips"] == "not_started"
    # changing the upstream idea makes what was made from it out of date
    proj.graph.upsert_section(
        SectionBodyV1(section_id="s", label="CHANGED"),
        interval=TimeInterval.from_seconds(0, 4),
    )
    assert _states(proj)["images"] == "in_progress"
    assert img  # (kept: the output still exists, only stale)


def test_active_job_marks_stage_in_progress(proj):
    s = stage_states(_genre().stages, proj, active_transforms=("clip.t",))
    assert {x.stage.slug: x.state for x in s}["clips"] == "in_progress"


def test_all_unknown_when_nothing_is_derivable(proj):
    only = (Stage("a", "A"),)
    assert [s.state for s in stage_states(only, proj)] == ["unknown"]


def test_price_none_is_unknown_never_free():
    g = _genre()
    p = stage_prices(g.stages, None)
    assert p[0].status == "free" and p[0].total_usd == 0.0
    assert all(x.total_usd is None and x.status == "unknown" for x in p[1:])
    boom = stage_prices(g.stages, lambda s: 1 / 0)
    assert boom[1].total_usd is None
    assert stage_prices(g.stages, lambda s: float("nan"))[1].total_usd is None


def test_overview_one_source_for_step_list_and_banner(proj):
    g = _genre("stg_demo_ov")
    prices = {"images": 6.0, "clips": 550.0, "voice": 4.0}
    ov = stage_overview(g, proj, quote=lambda s: prices[s.slug])
    assert ov["of"] == 4 and ov["step"] == 1 and not ov["complete"]
    # banner == sum of the step prices shown (the #305 disagreement, impossible now)
    assert ov["remaining_total_usd"] == sum(r["price"]["usd"] for r in ov["stages"])
    unknown = stage_overview(g, proj, quote=lambda s: None if s.slug == "clips" else 1.0)
    assert unknown["remaining_total_usd"] is None
    assert unknown["remaining_status"] == "unknown"


def test_overview_by_slug_and_step_advances(proj):
    nw.register_genre(_genre("stg_demo_slug"))
    try:
        _produce(proj, "img.t")
        ov = stage_overview("stg_demo_slug", proj, quote=lambda s: 1.0)
        assert ov["step"] == 1  # idea (a typed-in section) is not started
    finally:
        del nw.genres["stg_demo_slug"]
