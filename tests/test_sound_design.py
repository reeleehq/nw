"""The ``narration_to_sound_design.foley`` Transform (nw#190), against a fake foley.

foley is an extra (``nw[sound]``) and the suite never needs it: every test that
executes injects a fake ``foley`` module into ``sys.modules`` whose ``score``
records its call and returns a canned ``ScoreResult``-shaped object with a tiny
mix. The one test that reads the real foley (the defaults drift guard) skips
when it is not installed.
"""

from __future__ import annotations

import inspect
import json
import subprocess
import sys
import textwrap
from pathlib import Path
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import pytest
from falaw import current_fal_key, plan_to_dict
from lacing import Annotation, MediaRef, Provenance, RationalTime, TimeInterval

import nw
from nw._extras import MissingExtra
from nw.bodies import (
    NARRATION_TRACK_BODY_SCHEMA_URI,
    NARRATION_TRACK_TIER,
    SOUND_DESIGN_BODY_SCHEMA_URI,
    SOUND_DESIGN_CONFIG_BODY_SCHEMA_URI,
    SOUND_DESIGN_CONFIG_TIER,
    SOUND_DESIGN_TIER,
)
from nw.bodies.sound_design import DFLT_COMMERCIAL_OK, DFLT_MASTER, DFLT_MAX_EVENTS
from nw.graph import annotations_at_tier
from nw.transforms import TransformInputs
from nw.transforms.sound_design import (
    NAME,
    SOUND_DESIGN_TAGS,
    NarrationToSoundDesign,
)

SENTINEL = "sk-SENTINEL-sound-design-must-never-persist"
NARRATION_ASSET = "a" * 64
SEGMENTS = ["The door creaked open.", "Rain hammered the roof.", "She waited."]
SR = 8


# ---------------------------------------------------------------------------
# fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _isolated(tmp_path, monkeypatch):
    monkeypatch.setenv("FALAW_DATA_DIR", str(tmp_path / "_falaw"))
    monkeypatch.setenv("FALAW_CACHE_DIR", str(tmp_path / "_falaw" / "cache"))


@pytest.fixture
def project(tmp_path):
    p = nw.Project.init(tmp_path / "proj", title="Sound design")
    (p.root / "narration.wav").write_bytes(b"RIFF-fake-narration")
    return p


class _Serializable(SimpleNamespace):
    def to_dict(self):
        return dict(vars(self))


def _fake_foley(*, raises: Exception | None = None) -> ModuleType:
    """A ``foley`` stand-in: ``score`` records its call, ``audio.save`` writes."""
    mod = ModuleType("foley")
    mod.calls = []

    def score(segments, **kwargs):
        mod.calls.append({"segments": segments, **kwargs, "fal": current_fal_key()})
        if raises is not None:
            raise raises
        return SimpleNamespace(
            timeline=_Serializable(events=[{"sound_id": "door-creak", "at": 0.4}]),
            events=[
                _Serializable(segment=0, query="door creak", sound_id="door-creak")
            ],
            weave=SimpleNamespace(
                audio=[[0.0, 0.0]] * (SR * 2),  # 2 s of stereo silence
                sr=SR,
                credits=_Serializable(entries=[{"title": "Door creak", "by": "X"}]),
                captions_vtt="WEBVTT\n\n00:00.400 --> 00:01.000\n[door creaks]\n",
                master_report={"integrated_lufs": -16.0, "true_peak_dbtp": -1.0},
                notes=["word timings are estimates"],
            ),
        )

    def save(samples, sample_rate, dst, *, fmt="flac", subtype=None):
        Path(dst).write_bytes(f"{fmt}:{sample_rate}:{len(samples)}".encode())

    mod.score = score
    mod.audio = SimpleNamespace(save=save)
    return mod


def _authored(project, *, tier, uri, body, seconds=10.0) -> Annotation:
    ann = Annotation(
        id=uuid4(),
        tier=tier,
        reference=MediaRef(
            asset_id=project.graph.asset_id,
            interval=TimeInterval.from_seconds(0, seconds),
        ),
        body=body,
        body_schema_uri=uri,
        provenance=Provenance(
            was_generated_by="user:test",
            was_attributed_to="user:test",
            generated_at_time=RationalTime.now(),
            activity="create",
        ),
    )
    project.graph.add_annotation(ann)
    return ann


def _inputs(project, *, config=None, narration=None) -> TransformInputs:
    narration = narration or {
        "audio_path": "narration.wav",
        "artifact_id": NARRATION_ASSET,
        "segments": SEGMENTS,
    }
    track = _authored(
        project,
        tier=NARRATION_TRACK_TIER,
        uri=NARRATION_TRACK_BODY_SCHEMA_URI,
        body=narration,
    )
    cfg = _authored(
        project,
        tier=SOUND_DESIGN_CONFIG_TIER,
        uri=SOUND_DESIGN_CONFIG_BODY_SCHEMA_URI,
        body=config if config is not None else {},
    )
    return TransformInputs(
        primary=(track,), context={SOUND_DESIGN_CONFIG_BODY_SCHEMA_URI: (cfg,)}
    )


def _grep_tree(root) -> list:
    needle = SENTINEL.encode()
    return [
        str(p)
        for p in Path(root).rglob("*")
        if p.is_file() and needle in p.read_bytes()
    ]


# ---------------------------------------------------------------------------
# registration
# ---------------------------------------------------------------------------


def test_registered_with_its_kinds_and_rights_tags():
    t = nw.get_transform(NAME)
    assert isinstance(t, NarrationToSoundDesign)
    assert t.input_kinds == (
        NARRATION_TRACK_BODY_SCHEMA_URI,
        SOUND_DESIGN_CONFIG_BODY_SCHEMA_URI,
    )
    assert t.output_kind == SOUND_DESIGN_BODY_SCHEMA_URI
    assert t.generate_when == "static"
    assert NAME in nw.transforms.keys_with_tag("rights:licence-gate-fail-closed")
    assert set(SOUND_DESIGN_TAGS) >= {"cost:unknown"}
    (entry,) = [e for e in nw.transform_catalog() if e["name"] == NAME]
    json.dumps(entry)


# ---------------------------------------------------------------------------
# plan: pure data, cost unknown
# ---------------------------------------------------------------------------


def test_plan_is_pure_data_with_an_unknown_cost(project, monkeypatch):
    monkeypatch.setitem(sys.modules, "foley", None)  # planning must not need it
    t = nw.get_transform(NAME)
    inputs = _inputs(project)
    plan, (skel,) = t.plan(project, inputs)

    (call,) = plan.calls
    assert call.estimated_cost_usd is None
    assert plan.has_unknown_costs and plan.unknown_call_count == 1
    assert call.arguments["segments"] == SEGMENTS
    assert call.arguments["audio"] == str(project.root / "narration.wav")
    json.dumps(plan_to_dict(plan))

    assert skel.body_schema_uri == SOUND_DESIGN_BODY_SCHEMA_URI
    assert skel.body["artifact_id"] is None and skel.body["cache_key"]
    (track,) = inputs.primary
    (cfg,) = inputs.context[SOUND_DESIGN_CONFIG_BODY_SCHEMA_URI]
    assert skel.provenance.was_derived_from == [track.id, cfg.id, NARRATION_ASSET]
    assert skel.provenance.was_generated_by == f"transform:{NAME}@1"


def test_a_missing_config_is_refused(project):
    inputs = _inputs(project)
    with pytest.raises(ValueError, match="sound-design-config"):
        nw.get_transform(NAME).plan(project, TransformInputs(primary=inputs.primary))


# ---------------------------------------------------------------------------
# execute: foley.score, the mix, the annotation
# ---------------------------------------------------------------------------


def test_execute_scores_writes_the_mix_and_records_the_design(project, monkeypatch):
    foley = _fake_foley()
    monkeypatch.setitem(sys.modules, "foley", foley)
    t = nw.get_transform(NAME)
    inputs = _inputs(
        project,
        config={"max_events": 2, "master": "broadcast", "commercial_ok": False},
        narration={
            "audio_path": "narration.wav",
            "artifact_id": NARRATION_ASSET,
            "segments": SEGMENTS,
            "segment_starts": [0.0, 1.5, 3.0],
        },
    )
    plan, skeleton = t.plan(project, inputs)
    result = t.execute(project, plan, skeleton)

    (call,) = foley.calls
    assert call == {
        "segments": SEGMENTS,  # sentence-level, in render order
        "audio": str(project.root / "narration.wav"),
        "segment_starts": [0.0, 1.5, 3.0],
        "commercial_ok": False,
        "max_events": 2,
        "master": "broadcast",
        "fal": None,
    }

    (ann,) = result.annotations
    (artifact,) = result.artifacts
    body = ann.body
    assert body["artifact_id"] == artifact.asset_id and artifact.kind == "audio"
    assert (project.root / body["output_path"]).is_file()
    assert artifact.duration_s == 2.0 and artifact.cost_usd is None
    assert body["timeline"] == {"events": [{"sound_id": "door-creak", "at": 0.4}]}
    assert body["credits"] == {"entries": [{"title": "Door creak", "by": "X"}]}
    assert body["captions_vtt"].startswith("WEBVTT")
    assert body["master_report"]["integrated_lufs"] == -16.0
    assert body["notes"] == ["word timings are estimates"]
    assert body["events"][0]["sound_id"] == "door-creak"

    # provenance points at both inputs; the node is in the graph
    (track,) = inputs.primary
    (cfg,) = inputs.context[SOUND_DESIGN_CONFIG_BODY_SCHEMA_URI]
    assert {track.id, cfg.id} <= set(ann.provenance.was_derived_from)
    assert [a.id for a in annotations_at_tier(project.root, SOUND_DESIGN_TIER)] == [
        ann.id
    ]

    # cost: unknown, not $0
    assert result.has_unknown_costs is True
    assert result.cost_usd_actual == 0.0


def test_a_completed_design_is_reused_without_rescoring(project, monkeypatch):
    foley = _fake_foley()
    monkeypatch.setitem(sys.modules, "foley", foley)
    t = nw.get_transform(NAME)
    inputs = _inputs(project)
    t.execute(project, *t.plan(project, inputs))

    plan, skeleton = t.plan(project, inputs)
    assert plan.calls[0].cache_status == "hit" and not plan.has_unknown_costs
    again = t.execute(project, plan, skeleton)
    assert len(foley.calls) == 1
    assert again.has_unknown_costs is False and again.artifacts == ()
    assert again.annotations[0].body["artifact_id"]

    t.execute(project, *t.plan(project, inputs), force=True)  # "regenerate this"
    assert len(foley.calls) == 2


def test_impl_version_salts_the_plan_and_the_cache_key(project):
    class _Bumped(NarrationToSoundDesign):
        impl_version = "2"

    inputs = _inputs(project)
    plan1, (skel1,) = nw.get_transform(NAME).plan(project, inputs)
    plan2, (skel2,) = _Bumped().plan(project, inputs)
    assert plan1.calls[0].key_extra == {}
    assert plan2.calls[0].key_extra == {"transform_impl": "2"}
    assert skel1.body["cache_key"] != skel2.body["cache_key"]
    assert skel2.provenance.was_generated_by == f"transform:{NAME}@2"


# ---------------------------------------------------------------------------
# off means unscheduled
# ---------------------------------------------------------------------------


def test_a_disabled_config_schedules_nothing_and_spends_nothing(project, monkeypatch):
    monkeypatch.setitem(sys.modules, "foley", None)  # would raise if reached
    t = nw.get_transform(NAME)
    plan, skeleton = t.plan(project, _inputs(project, config={"enabled": False}))
    assert plan.calls == () and skeleton == ()

    result = t.execute(project, plan, skeleton)
    assert result.annotations == () and result.artifacts == ()
    assert result.has_unknown_costs is False and result.cost_usd_actual == 0.0
    assert annotations_at_tier(project.root, SOUND_DESIGN_TIER) == []


# ---------------------------------------------------------------------------
# the extra
# ---------------------------------------------------------------------------


def test_executing_without_foley_names_the_extra(project, monkeypatch):
    t = nw.get_transform(NAME)
    plan, skeleton = t.plan(project, _inputs(project))
    monkeypatch.setitem(sys.modules, "foley", None)
    with pytest.raises(MissingExtra, match=r"nw\[sound\]"):
        t.execute(project, plan, skeleton)
    assert isinstance(MissingExtra("x"), ImportError)


def test_import_nw_does_not_load_foley():
    import os

    repo = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                """
                import sys, nw
                assert nw.get_transform("narration_to_sound_design.foley")
                print(sys.modules.get("foley") is None)
                """
            ),
        ],
        capture_output=True,
        text=True,
        cwd=repo,
        # this checkout's nw, not whichever one an editable install points at
        env={**os.environ, "PYTHONPATH": str(repo)},
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "True"


def test_config_defaults_match_foley_score():
    foley = pytest.importorskip("foley")
    params = inspect.signature(foley.score).parameters
    assert params["max_events"].default == DFLT_MAX_EVENTS
    assert params["master"].default == DFLT_MASTER
    from foley.licensing import DEFAULT_INTENDED_USE

    assert DEFAULT_INTENDED_USE.commercial is DFLT_COMMERCIAL_OK


# ---------------------------------------------------------------------------
# secrets and failures
# ---------------------------------------------------------------------------


def test_a_secret_reaches_foley_bound_and_is_never_persisted(
    project, monkeypatch, caplog
):
    foley = _fake_foley()
    monkeypatch.setitem(sys.modules, "foley", foley)
    t = nw.get_transform(NAME)
    plan, skeleton = t.plan(project, _inputs(project))
    result = t.execute(project, plan, skeleton, secrets={"fal": SENTINEL})

    assert foley.calls[0]["fal"] == SENTINEL  # bound for the call
    assert current_fal_key() is None  # and released
    assert SENTINEL not in json.dumps(plan_to_dict(plan))
    assert SENTINEL not in json.dumps(
        [a.model_dump(mode="json") for a in result.annotations]
    )
    assert _grep_tree(project.root) == []
    assert SENTINEL not in caplog.text


def test_isolate_records_a_redacted_unproduced_output(project, monkeypatch):
    foley = _fake_foley(raises=RuntimeError(f"401: key {SENTINEL} rejected"))
    monkeypatch.setitem(sys.modules, "foley", foley)
    t = nw.get_transform(NAME)
    plan, skeleton = t.plan(project, _inputs(project))

    result = t.execute(
        project, plan, skeleton, on_failure="isolate", secrets={"fal": SENTINEL}
    )
    (failed,) = result.failed
    assert result.annotations == () and result.has_unknown_costs is True
    assert SENTINEL not in failed.reason and "<redacted:fal>" in failed.reason
    assert len(project.graph.unproduced_outputs()) == 1
    assert _grep_tree(project.root) == []

    with pytest.raises(RuntimeError):
        t.execute(project, plan, skeleton)  # halt: the original propagates


# ---------------------------------------------------------------------------
# the host seam
# ---------------------------------------------------------------------------


def test_a_host_subclass_supplies_its_own_extraction(project):
    class _HostShaped(NarrationToSoundDesign):
        name = "test.host_sound_design"

        def narration_segments(self, narration):
            return [b["text"] for b in narration.body["beats"]]

        def narration_audio_path(self, project, narration):
            return Path("/elsewhere/mix.wav")

        def narration_segment_starts(self, narration):
            return [b["start"] for b in narration.body["beats"]]

    host_node = Annotation(
        id=uuid4(),
        tier="host-narration",
        reference=MediaRef(
            asset_id=project.graph.asset_id, interval=TimeInterval.from_seconds(0, 4)
        ),
        body={
            "beats": [{"text": "One.", "start": 0.0}, {"text": "Two.", "start": 2.0}]
        },
        body_schema_uri="annot://schema/host-narration/v1",
        provenance=Provenance(
            was_generated_by="user:test",
            was_attributed_to="user:test",
            generated_at_time=RationalTime.now(),
            activity="create",
        ),
    )
    cfg = _inputs(project).context
    plan, (skel,) = _HostShaped().plan(
        project, TransformInputs(primary=(host_node,), context=cfg)
    )
    args = plan.calls[0].arguments
    assert args["segments"] == ["One.", "Two."]
    assert args["segment_starts"] == [0.0, 2.0]
    assert args["audio"] == str(Path("/elsewhere/mix.wav"))
    assert host_node.id in skel.provenance.was_derived_from
