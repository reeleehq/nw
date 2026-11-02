"""``narration_to_sound_design.foley`` — a narration track, sound-designed by foley (nw#190).

Inputs ``(narration-track/v1, sound-design-config/v1)``, output
``sound-design/v1`` (:mod:`nw.bodies.sound_design`): ``foley.score`` chooses
sounds for the narration's sentences under its fail-closed licence gate, weaves
them into the narration audio and masters the mix. The mix is written to
``data/sound_design/<annotation id>.flac`` as an audio :class:`lacing.Artifact`
the annotation names by ``artifact_id``; the annotation carries foley's editable
timeline, the per-event rationale, the credits, SDH captions, the master report
and foley's notes.

The contract, rule by rule:

- **``plan()`` is pure data.** It reads the two input annotations (and, for a
  re-run, the graph) and returns one *descriptive* :class:`falaw.CallPlan`
  (``backend="foley"``, ``application="foley.score"``) whose ``arguments`` are
  exactly what ``execute`` will hand ``foley.score``, plus the skeleton. foley
  is not imported and nothing is called. ``backend="foley"`` is registered with
  no falaw executor on purpose: this Transform's ``execute`` runs the call, and
  a caller that pushes the plan through ``falaw.execute_plan`` instead fails
  loudly at the backend lookup rather than silently doing nothing.
- **Cost is unknown, never $0.** foley may spend (an LLM rung, a generation
  fallback) and ``ScoreResult`` reports no spend, so the call's
  ``estimated_cost_usd`` is ``None`` (``Plan.has_unknown_costs`` is true and a
  cost gate asks for approval) and ``execute`` reports
  ``has_unknown_costs=True`` for every run it made. The one known figure is a
  cache hit: a completed sound design under the same ``cache_key`` (which folds
  ``impl_version``) is reused at plan time (``cache_status="hit"``) and at
  execute time, at no spend.
- **Off means unscheduled.** A config with ``enabled=False`` plans no call and
  no skeleton, and ``execute`` on that empty plan produces nothing and imports
  nothing.
- **foley is an extra** (``nw[sound]``). It is imported inside ``execute`` only;
  without it, ``execute`` raises :class:`nw._extras.MissingExtra` (an
  ``ImportError``) naming ``nw[sound]``. Registering this Transform, and
  ``import nw``, never load it.
- **Secrets** reach foley only by being bound for the call
  (:func:`nw.secrets.using_secrets`: a ``"fal"`` secret is the fal credential);
  they enter no argument, body, plan, key or record. A failure reason is
  redacted before it is persisted.

**Hosts with their own narration schema** subclass with their own
``input_kinds`` (the config stays the second kind) and override the small
extraction methods — :meth:`~NarrationToSoundDesign.narration_segments`,
:meth:`~NarrationToSoundDesign.narration_audio_path` and, optionally,
:meth:`~NarrationToSoundDesign.narration_segment_starts` — instead of
converting their nodes to ``narration-track/v1``.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import replace
from pathlib import Path
from typing import Optional
from uuid import uuid4

from falaw import CallPlan, Plan
from lacing import Annotation, Artifact

from nw._extras import is_missing, missing_extra
from nw.bodies.sound_design import (
    NARRATION_TRACK_BODY_SCHEMA_URI,
    SOUND_DESIGN_BODY_SCHEMA_URI,
    SOUND_DESIGN_CONFIG_BODY_SCHEMA_URI,
    SOUND_DESIGN_TIER,
    NarrationTrackBodyV1,
    SoundDesignBodyV1,
    SoundDesignConfigBodyV1,
)
from nw.secrets import as_secrets, redact, redact_exception, using_secrets
from nw.transforms import (
    BaseTransform,
    FailedOutput,
    OnFailure,
    TransformInputs,
    TransformResult,
    cache_key,
    cached_output,
    register_transform,
    resolve_cache_mode,
    stamp_transform_identity,
)
from nw.transforms._provenance import derive_provenance
from nw.transforms.asset_refs import asset_refs_of

NAME = "narration_to_sound_design.foley"
SOUND_EXTRA = "sound"
FOLEY_PACKAGE = "foley"

SOUND_DESIGN_TOOL = "sound_design"
SOUND_DESIGN_APPLICATION = "foley.score"
SOUND_DESIGN_BACKEND = "foley"
"""The descriptive call's backend: no falaw executor exists for it (see above)."""

AUDIO_FORMAT = "flac"
"""The mix's container (foley's lossless archive format)."""
AUDIO_MIME = "audio/flac"
SOUND_DESIGN_DIR = Path("data", "sound_design")
"""Where mixes land, relative to the project root."""

CACHE_TAG = "sound-design"
"""The leading part of every ``cache_key`` this Transform mints."""

SOUND_DESIGN_TAGS = (
    "rights:licence-gate-fail-closed",
    "rights:intent-commercial-by-default",
    "cost:unknown",
)
"""Registry tags: foley refuses a sound whose licence does not fit the intent;
the intent is the config's ``commercial_ok`` (default: commercial publishing);
and what a run spends is not known in advance."""


def _import_foley():
    """``foley``, or a :class:`~nw._extras.MissingExtra` naming ``nw[sound]``."""
    try:
        import foley
    except ModuleNotFoundError as e:
        if is_missing(e, FOLEY_PACKAGE):
            raise missing_extra(
                f"The {NAME!r} transform", extra=SOUND_EXTRA, package=FOLEY_PACKAGE
            ) from e
        raise
    return foley


class NarrationToSoundDesign(BaseTransform):
    """``narration-track/v1`` + ``sound-design-config/v1`` → ``sound-design/v1``."""

    name = NAME
    input_kinds = (NARRATION_TRACK_BODY_SCHEMA_URI, SOUND_DESIGN_CONFIG_BODY_SCHEMA_URI)
    output_kind = SOUND_DESIGN_BODY_SCHEMA_URI
    generate_when = "static"  # one sound design per narration track
    attributed_to = f"agent:{NAME}"

    # --- host seams: how a narration node yields what foley needs -------------

    def narration_segments(self, narration: Annotation) -> list[str]:
        """Sentence-level narration text, in render order."""
        return list(NarrationTrackBodyV1.model_validate(narration.body).segments)

    def narration_audio_path(self, project, narration: Annotation) -> Path:
        """The one narration audio file foley aligns and weaves into."""
        path = Path(NarrationTrackBodyV1.model_validate(narration.body).audio_path)
        return path if path.is_absolute() else Path(project.root) / path

    def narration_segment_starts(self, narration: Annotation) -> Optional[list[float]]:
        """Each segment's start in the audio (seconds), or ``None`` to align the file."""
        return NarrationTrackBodyV1.model_validate(narration.body).segment_starts

    # --- plan: pure data -------------------------------------------------------

    def config(self, inputs: TransformInputs) -> SoundDesignConfigBodyV1:
        """The one config annotation in ``inputs.context``, validated."""
        found = inputs.context.get(self.input_kinds[1], ())
        if len(found) != 1:
            raise ValueError(
                f"{self.name}: expected exactly one {self.input_kinds[1]} "
                f"annotation in inputs.context, got {len(found)}. Add a "
                "sound-design-config annotation (enabled=False to turn sound "
                "design off)."
            )
        return SoundDesignConfigBodyV1.model_validate(found[0].body)

    def plan(
        self, project, inputs: TransformInputs, *, params=None
    ) -> tuple[Plan, tuple[Annotation, ...]]:
        narration = inputs.primary[0]
        config = self.config(inputs)
        if not config.enabled:
            return Plan(calls=()), ()
        segments = self.narration_segments(narration)
        starts = self.narration_segment_starts(narration)
        arguments = {
            "segments": segments,
            "audio": str(self.narration_audio_path(project, narration)),
            "segment_starts": starts,
            "commercial_ok": config.commercial_ok,
            "max_events": config.max_events,
            "master": config.master,
        }
        # The narration's identity is its audio's content id when its schema
        # declares one, else the node itself: never the path, which says
        # nothing about the bytes.
        audio_identity = ",".join(asset_refs_of(narration)) or f"node:{narration.id}"
        key = cache_key(
            self,
            CACHE_TAG,
            audio_identity,
            json.dumps(segments),
            json.dumps(starts),
            json.dumps(config.model_dump(), sort_keys=True),
        )
        context = {self.input_kinds[1]: inputs.context[self.input_kinds[1]]}
        skeleton = Annotation(
            id=uuid4(),
            tier=SOUND_DESIGN_TIER,
            reference=narration.reference,
            body=SoundDesignBodyV1(cache_key=key).model_dump(),
            body_schema_uri=self.output_kind,
            provenance=derive_provenance(
                self,
                TransformInputs(primary=(narration,), context=context),
                attributed_to=self.attributed_to,
            ),
        )
        call = CallPlan(
            tool=SOUND_DESIGN_TOOL,
            application=SOUND_DESIGN_APPLICATION,
            backend=SOUND_DESIGN_BACKEND,
            arguments=arguments,
            output_kind="audio",
            estimated_cost_usd=None,  # unknown, never free
            metadata={"narration_id": str(narration.id)},
        )
        plan = stamp_transform_identity(Plan(calls=(call,)), self)
        # The peek is keyed by `cache_key`, which already folds impl_version,
        # so it stays valid after the stamp reset `cache_status`.
        if cached_output(project.root, SOUND_DESIGN_TIER, key) is not None:
            plan = Plan(calls=(replace(plan.calls[0], cache_status="hit"),))
        return plan, (skeleton,)

    # --- execute: the one place foley runs -------------------------------------

    def execute(
        self,
        project,
        plan: Plan,
        skeleton: tuple[Annotation, ...],
        *,
        use_cache: bool = True,
        force: bool = False,
        on_failure: OnFailure = "halt",
        unit_instance_id: Optional[str] = None,
        secrets: Optional[Mapping[str, str]] = None,
    ) -> TransformResult:
        if len(skeleton) != len(plan.calls):
            raise ValueError(
                f"{self.name}.execute: plan has {len(plan.calls)} calls but "
                f"skeleton has {len(skeleton)}; pass what plan() returned together."
            )
        if on_failure not in ("halt", "isolate"):
            raise ValueError(
                f"on_failure must be 'halt' or 'isolate', got {on_failure!r}"
            )
        cache_on, refresh = resolve_cache_mode(use_cache=use_cache, force=force)
        plan = stamp_transform_identity(plan, self)
        secrets = as_secrets(secrets)
        foley = None
        completed, artifacts, failed = [], [], []
        ran = False
        for i, (call, skel) in enumerate(zip(plan.calls, skeleton, strict=True)):
            hit = None
            if cache_on and not refresh:
                hit = cached_output(
                    project.root, SOUND_DESIGN_TIER, skel.body["cache_key"]
                )
            if hit is not None:
                ann = skel.model_copy(update={"body": dict(hit.body)})
            else:
                foley = foley or _import_foley()
                ran = True
                try:
                    ann, artifact = self._score(foley, project, call, skel, secrets)
                except Exception as e:  # noqa: BLE001 — the policy decides
                    if on_failure == "halt":
                        raise
                    e = redact_exception(e, secrets)
                    reason = redact(f"{type(e).__name__}: {e}", secrets)
                    project.graph.add_unproduced_output(
                        skel,
                        transform_name=self.name,
                        status="failed",
                        reason=reason,
                        error=e,
                        instance_id=unit_instance_id,
                        call_index=i,
                    )
                    failed.append(
                        FailedOutput(
                            skeleton=skel, status="failed", reason=reason, error=e
                        )
                    )
                    continue
                artifacts.append(artifact)
            project.graph.add_annotation(
                ann, instance_id=unit_instance_id, call_index=i
            )
            completed.append(ann)
        return TransformResult(
            annotations=tuple(completed),
            artifacts=tuple(artifacts),
            cost_usd_actual=0.0,  # a lower bound: foley reports no spend
            cache_hit_savings_usd=0.0,
            has_unknown_costs=ran,  # a run (even a failed one) may have spent
            failed=tuple(failed),
        )

    def _score(self, foley, project, call: CallPlan, skel: Annotation, secrets):
        """Run ``foley.score`` for one call; write the mix; complete ``skel``."""
        args = call.arguments
        with using_secrets(secrets):
            scored = foley.score(
                list(args["segments"]),
                audio=args["audio"],
                segment_starts=args["segment_starts"],
                commercial_ok=args["commercial_ok"],
                max_events=args["max_events"],
                master=args["master"],
            )
        woven = scored.weave
        if woven is None:
            raise RuntimeError(
                f"{self.name}: foley.score returned no mix for {args['audio']!r}."
            )
        rel = SOUND_DESIGN_DIR / f"{skel.id}.{AUDIO_FORMAT}"
        out = Path(project.root) / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        foley.audio.save(woven.audio, woven.sr, out, fmt=AUDIO_FORMAT)
        artifact = Artifact.from_path(
            out,
            kind="audio",
            was_generated_by=f"transform:{self.name}@{self.impl_version}",
            was_attributed_to=self.attributed_to,
            was_derived_from=tuple(str(x) for x in skel.provenance.was_derived_from),
            duration_s=len(woven.audio) / woven.sr,
            mime=AUDIO_MIME,
            cost_usd=None,  # unknown, never free
        )
        body = SoundDesignBodyV1(
            artifact_id=artifact.asset_id,
            output_path=rel.as_posix(),
            cache_key=skel.body["cache_key"],
            timeline=scored.timeline.to_dict(),
            events=[e.to_dict() for e in scored.events],
            credits=woven.credits.to_dict(),
            captions_vtt=woven.captions_vtt,
            master_report=dict(woven.master_report),
            notes=[str(n) for n in woven.notes],
        )
        return skel.model_copy(update={"body": body.model_dump()}), artifact


register_transform(NAME, NarrationToSoundDesign(), tags=SOUND_DESIGN_TAGS)
