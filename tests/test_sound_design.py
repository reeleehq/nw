"""The ``narration_to_sound_design.foley`` Transform (nw#190).

foley is an extra (``nw[sound]``) and most of this file never needs it: those
tests inject a fake ``foley`` whose ``score`` has the real keyword-only
signature (pinned against foley's own when it is installed), records its call
and returns a canned ``ScoreResult``-shaped object. The tests that read the
real foley — the signature and defaults guards, and one offline end-to-end run
on an in-memory library with generation off — skip when it is not installed.
The suite's autouse guard (``tests/conftest.py``) refuses outbound sockets and
isolates falaw's cache and content store throughout.
"""

from __future__ import annotations

import functools
import importlib.util
import inspect
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from types import ModuleType, SimpleNamespace
from uuid import uuid4

import pytest
from falaw import current_fal_key, plan_to_dict
from falaw.content import default_content_store
from lacing import Annotation, MediaRef, Provenance, RationalTime, TimeInterval
from pydantic import ValidationError

import nw
from nw._extras import MissingExtra
from nw.bodies import (
    NARRATION_TRACK_BODY_SCHEMA_URI,
    NARRATION_TRACK_TIER,
    SOUND_DESIGN_BODY_SCHEMA_URI,
    SOUND_DESIGN_CONFIG_BODY_SCHEMA_URI,
    SOUND_DESIGN_CONFIG_TIER,
    SOUND_DESIGN_TIER,
    NarrationTrackBodyV1,
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
HAS_FOLEY = importlib.util.find_spec("foley") is not None
needs_foley = pytest.mark.skipif(not HAS_FOLEY, reason="needs the nw[sound] extra")


# ---------------------------------------------------------------------------
# fixtures + helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def project(tmp_path):
    p = nw.Project.init(tmp_path / "proj", title="Sound design")
    (p.root / "narration.wav").write_bytes(b"RIFF-fake-narration")
    return p


class _Serializable(SimpleNamespace):
    def to_dict(self):
        return dict(vars(self))


def _fake_foley(*, raises: Exception | None = None) -> ModuleType:
    """A ``foley`` stand-in: ``score`` records its call, ``audio.save`` encodes."""
    mod = ModuleType("foley")
    mod.calls = []

    def score(  # foley.score's signature, pinned by a test below
        segments,
        *,
        audio=None,
        transcript=None,
        segment_starts=None,
        library=None,
        intended_use=None,
        commercial_ok=None,
        max_events=6,
        verify="listen",
        backend="auto",
        allow_generate=True,
        master="podcast",
        weave=None,
        llm=None,
        budget=None,
        **weave_kwargs,
    ):
        mod.calls.append(
            {
                "segments": segments,
                "audio": audio,
                "segment_starts": segment_starts,
                "commercial_ok": commercial_ok,
                "max_events": max_events,
                "master": master,
                "fal": current_fal_key(),
            }
        )
        if raises is not None:
            raise raises
        return SimpleNamespace(
            timeline=_Serializable(items=({"sound_id": "door-creak", "at": 0.4},)),
            events=[
                _Serializable(segment=0, query="door creak", sound_id="door-creak")
            ],
            weave=SimpleNamespace(
                audio=[[0.0, 0.0]] * (SR * 2),  # 2 s of stereo silence
                sr=SR,
                credits=_Serializable(entries=({"title": "Door creak", "by": "X"},)),
                captions_vtt="WEBVTT\n\n00:00.400 --> 00:01.000\n[door creaks]\n",
                master_report={"integrated_lufs": -16.0, "true_peak_dbtp": -1.0},
                notes=["word timings are estimates"],
            ),
        )

    def save(samples, sample_rate, dst, *, fmt="flac", subtype="PCM_24"):
        dst.write(f"{fmt}:{sample_rate}:{len(samples)}".encode())

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
# registration and the narration body
# ---------------------------------------------------------------------------


def test_registered_with_its_kinds_rights_tags_and_backend():
    from falaw.backends import backends

    t = nw.get_transform(NAME)
    assert isinstance(t, NarrationToSoundDesign)
    assert t.input_kinds == (
        NARRATION_TRACK_BODY_SCHEMA_URI,
        SOUND_DESIGN_CONFIG_BODY_SCHEMA_URI,
    )
    assert t.output_kind == SOUND_DESIGN_BODY_SCHEMA_URI
    assert t.generate_when == "static"
    assert NAME in nw.transforms.keys_with_tag("rights:licence-gate-fail-closed")
    assert "cost:unknown" in SOUND_DESIGN_TAGS
    assert "foley" in backends
    (entry,) = [e for e in nw.transform_catalog() if e["name"] == NAME]
    json.dumps(entry)


@pytest.mark.parametrize(
    "path", ["/abs/narration.wav", "../narration.wav", "a/../../x.wav", "C:\\n.wav"]
)
def test_the_narration_path_stays_inside_the_project(path):
    with pytest.raises(ValidationError, match="audio_path"):
        NarrationTrackBodyV1(audio_path=path, segments=["x"])


# ---------------------------------------------------------------------------
# plan: pure data, cost unknown, keyed on the audio's content
# ---------------------------------------------------------------------------


def test_plan_is_pure_data_with_an_unknown_cost(project, monkeypatch):
    monkeypatch.setitem(sys.modules, "foley", None)  # planning must not need it
    t = nw.get_transform(NAME)
    inputs = _inputs(project)
    plan, (skel,) = t.plan(project, inputs)

    (call,) = plan.calls
    assert call.backend == "foley" and call.estimated_cost_usd is None
    assert plan.has_unknown_costs and plan.unknown_call_count == 1
    assert call.arguments["segments"] == SEGMENTS
    from lacing import hash_file

    assert call.arguments["audio"] == {
        "path": "narration.wav",  # project-relative; resolved at execution
        "sha256": hash_file(project.root / "narration.wav"),
    }
    json.dumps(plan_to_dict(plan))

    assert skel.body_schema_uri == SOUND_DESIGN_BODY_SCHEMA_URI
    assert skel.body["artifact_id"] is None
    (track,) = inputs.primary
    (cfg,) = inputs.context[SOUND_DESIGN_CONFIG_BODY_SCHEMA_URI]
    assert skel.provenance.was_derived_from == [track.id, cfg.id, NARRATION_ASSET]
    assert skel.provenance.was_generated_by == f"transform:{NAME}@1"


def test_inputs_must_be_one_narration_and_one_config(project):
    t = nw.get_transform(NAME)
    inputs = _inputs(project)
    with pytest.raises(ValueError, match="sound-design-config"):
        t.plan(project, TransformInputs(primary=inputs.primary))
    two = TransformInputs(primary=inputs.primary * 2, context=inputs.context)
    with pytest.raises(ValueError, match="exactly one"):
        t.plan(project, two)


def test_changed_bytes_or_path_is_a_cache_miss(project, monkeypatch):
    foley = _fake_foley()
    monkeypatch.setitem(sys.modules, "foley", foley)
    t = nw.get_transform(NAME)
    inputs = _inputs(project)
    t.execute(project, *t.plan(project, inputs))
    assert t.plan(project, inputs)[0].calls[0].cache_status == "hit"

    (project.root / "narration.wav").write_bytes(b"RIFF-re-recorded")
    plan, skeleton = t.plan(project, inputs)
    assert plan.calls[0].cache_status != "hit" and plan.has_unknown_costs
    t.execute(project, plan, skeleton)
    assert len(foley.calls) == 2

    (project.root / "moved.wav").write_bytes(b"RIFF-re-recorded")
    moved = _inputs(
        project, narration={"audio_path": "moved.wav", "segments": SEGMENTS}
    )
    assert t.plan(project, moved)[0].calls[0].cache_status != "hit"


def test_bytes_changed_after_planning_are_refused(project, monkeypatch):
    monkeypatch.setitem(sys.modules, "foley", _fake_foley())
    t = nw.get_transform(NAME)
    plan, skeleton = t.plan(project, _inputs(project))
    (project.root / "narration.wav").write_bytes(b"RIFF-swapped-under-the-plan")
    with pytest.raises(ValueError, match="plan again"):
        t.execute(project, plan, skeleton)


def test_impl_version_salts_the_call(project):
    class _Bumped(NarrationToSoundDesign):
        impl_version = "2"

    inputs = _inputs(project)
    plan1, _ = nw.get_transform(NAME).plan(project, inputs)
    plan2, (skel2,) = _Bumped().plan(project, inputs)
    assert plan1.calls[0].key_extra == {}
    assert plan2.calls[0].key_extra == {"transform_impl": "2"}
    assert skel2.provenance.was_generated_by == f"transform:{NAME}@2"


# ---------------------------------------------------------------------------
# execute: through BaseTransform and falaw, with the foley backend
# ---------------------------------------------------------------------------


def test_execute_scores_stores_the_mix_and_records_the_design(project, monkeypatch):
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
    body = ann.body
    mix = default_content_store().get_blob(body["artifact_id"])
    assert mix == f"flac:{SR}:{SR * 2}".encode()
    assert body["duration_s"] == 2.0
    # foley's tuples arrive as lists: the body returned is the body stored
    assert body["timeline"] == {"items": [{"sound_id": "door-creak", "at": 0.4}]}
    assert body["credits"] == {"entries": [{"title": "Door creak", "by": "X"}]}
    assert body["captions_vtt"].startswith("WEBVTT")
    assert body["master_report"]["integrated_lufs"] == -16.0
    assert body["notes"] == ["word timings are estimates"]
    assert body["events"][0]["sound_id"] == "door-creak"
    (stored,) = annotations_at_tier(project.root, SOUND_DESIGN_TIER)
    assert stored.id == ann.id and stored.body == body

    (track,) = inputs.primary
    (cfg,) = inputs.context[SOUND_DESIGN_CONFIG_BODY_SCHEMA_URI]
    assert {track.id, cfg.id} <= set(ann.provenance.was_derived_from)

    assert result.has_unknown_costs is True  # unknown, not $0
    assert result.cost_usd_actual == 0.0


def test_a_cached_call_is_reused_without_rescoring(project, monkeypatch):
    foley = _fake_foley()
    monkeypatch.setitem(sys.modules, "foley", foley)
    t = nw.get_transform(NAME)
    inputs = _inputs(project)
    first = t.execute(project, *t.plan(project, inputs))

    plan, skeleton = t.plan(project, inputs)
    assert plan.calls[0].cache_status == "hit" and not plan.has_unknown_costs
    again = t.execute(project, plan, skeleton)
    assert len(foley.calls) == 1
    assert again.has_unknown_costs is False and again.cost_usd_actual == 0.0
    assert again.annotations[0].body == first.annotations[0].body

    t.execute(project, *t.plan(project, inputs), force=True)  # "regenerate this"
    assert len(foley.calls) == 2


def test_the_executor_refuses_to_run_without_a_project(project, monkeypatch):
    from falaw import execute_plan

    monkeypatch.setitem(sys.modules, "foley", _fake_foley())
    plan, _ = nw.get_transform(NAME).plan(project, _inputs(project))
    with pytest.raises(RuntimeError, match="no project is bound"):
        execute_plan(plan)


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


def test_import_nw_does_not_load_foley():
    repo = Path(__file__).resolve().parents[1]
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            textwrap.dedent(
                """
                import sys, nw
                from falaw.backends import backends
                assert nw.get_transform("narration_to_sound_design.foley")
                assert "foley" in backends
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


@needs_foley
def test_config_defaults_and_the_fake_signature_match_foley():
    import foley

    real = inspect.signature(foley.score).parameters
    assert real["max_events"].default == DFLT_MAX_EVENTS
    assert real["master"].default == DFLT_MASTER
    from foley.licensing import DEFAULT_INTENDED_USE

    assert DEFAULT_INTENDED_USE.commercial is DFLT_COMMERCIAL_OK

    fake = inspect.signature(_fake_foley().score).parameters
    shape = lambda ps: [(p.name, p.kind, p.default) for p in ps.values()]  # noqa: E731
    assert shape(fake) == shape(real)


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
    assert _grep_tree(Path(os.environ["FALAW_CACHE_DIR"])) == []
    assert SENTINEL not in caplog.text


def test_isolate_records_an_unproduced_output(project, monkeypatch):
    foley = _fake_foley(raises=RuntimeError("no sound fits"))
    monkeypatch.setitem(sys.modules, "foley", foley)
    t = nw.get_transform(NAME)
    plan, skeleton = t.plan(project, _inputs(project))

    result = t.execute(project, plan, skeleton, on_failure="isolate")
    (failed,) = result.failed
    # BaseTransform's rule: a failed call's spend is not counted (a lower bound)
    assert result.annotations == () and "no sound fits" in str(failed.error)
    assert len(project.graph.unproduced_outputs()) == 1

    with pytest.raises(RuntimeError, match="no sound fits"):
        t.execute(project, *t.plan(project, _inputs(project)))  # halt


# ---------------------------------------------------------------------------
# the host seam
# ---------------------------------------------------------------------------


def test_a_host_subclass_supplies_its_own_extraction(project):
    (project.root / "beats").mkdir()
    (project.root / "beats" / "mix.wav").write_bytes(b"RIFF-host")

    class _HostShaped(NarrationToSoundDesign):
        name = "test.host_sound_design"

        def narration_segments(self, narration):
            return [b["text"] for b in narration.body["beats"]]

        def narration_audio_path(self, project, narration):
            return Path("beats", "mix.wav")

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
    assert args["audio"]["path"] == "beats/mix.wav"
    assert host_node.id in skel.provenance.was_derived_from


# ---------------------------------------------------------------------------
# the real foley, offline: an in-memory library, generation off
# ---------------------------------------------------------------------------


def _in_memory_library(foley, np):
    """foley's test FakeLibrary, reduced: three CC0 sounds with real audio."""
    from foley.audio import WORKING_SAMPLE_RATE, to_working
    from foley.base import Candidate, LicenseRecord, SoundRecord, StorageMode

    sr = WORKING_SAMPLE_RATE
    licence = LicenseRecord(
        source="user", license_id="CC0-1.0", commercial_ok=True, rights_verified=True
    )
    recs = {
        sid: SoundRecord(
            id=sid,
            caption=caption,
            tags=[sid],
            duration_s=0.5,
            storage_mode=StorageMode.by_value,
            uri=f"memory://{sid}",
            license=licence,
        )
        for sid, caption in [
            ("door", "door creak"),
            ("rain", "rain bed"),
            ("thunder", "thunder rumble"),
        ]
    }
    tone = (0.3 * np.sin(2 * np.pi * 220 * np.arange(sr // 2) / sr)).astype("float32")

    class _Library:
        def __getitem__(self, k):
            return recs[k]

        def __contains__(self, k):
            return k in recs

        def array(self, ref, *, sr=None, mono=True):
            target = WORKING_SAMPLE_RATE if sr is None else sr
            return to_working(tone, WORKING_SAMPLE_RATE, mono=mono, target_sr=target)

        def _cands(self, ids, k):
            return [
                Candidate(
                    sound=recs[i], clap_score=0.9 - 0.1 * n, rrf_score=0.8 - 0.1 * n
                )
                for n, i in enumerate(ids[:k])
            ]

        def search(self, query, *, k=10, **kw):
            return self._cands(list(recs), k)

        def similar(self, sound_id, *, k=10):
            return self._cands([i for i in recs if i != sound_id], k)

        def search_clip(self, clip, *, k=10):
            return self._cands(list(recs), k)

    return _Library()


@needs_foley
def test_the_real_foley_offline(project, monkeypatch):
    np = pytest.importorskip("numpy")
    sf = pytest.importorskip("soundfile")
    import foley
    from foley.weave.align import FakeAligner

    foley.obs.configure(run_store={})  # no run manifests on the user's disk
    try:
        monkeypatch.setattr(
            foley,
            "score",
            functools.partial(
                foley.score,
                library=_in_memory_library(foley, np),
                allow_generate=False,
                llm="fake",
                aligner=FakeAligner(),
            ),
        )
        rate = 48000
        noise = 0.1 * np.random.default_rng(0).standard_normal(3 * rate)
        sf.write(project.root / "narration.wav", noise.astype("float32"), rate)

        t = nw.get_transform(NAME)
        result = t.execute(project, *t.plan(project, _inputs(project)))
    finally:
        foley.obs.reset()

    (ann,) = result.annotations
    mix = default_content_store().get_blob(ann.body["artifact_id"])
    assert mix[:4] == b"fLaC"
    assert ann.body["duration_s"] > 0
    assert ann.body["captions_vtt"].startswith("WEBVTT")
    assert ann.body["timeline"] and ann.body["master_report"]
    assert result.has_unknown_costs is True
