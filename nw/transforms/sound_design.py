"""``narration_to_sound_design.foley`` — a narration track, sound-designed by foley (nw#190).

Inputs ``(narration-track/v1, sound-design-config/v1)``, output
``sound-design/v1`` (:mod:`nw.bodies.sound_design`): ``foley.score`` chooses
sounds for the narration's sentences under its fail-closed licence gate, weaves
them into the narration audio and masters the mix.

**A strategy, not a second executor.** The work runs as a falaw call on its own
backend: this module registers an in-process executor for ``backend="foley"``
in :data:`falaw.backends.backends`, and the Transform is an ordinary
:class:`~nw.transforms.BaseTransform`. So everything ``BaseTransform.execute``
owns (cache read/write halves, the ``impl_version`` stamp, the secret binding,
``halt``/``isolate`` and unproduced-output records, observed cost) applies
unchanged, and falaw's cache is the compare-and-skip. It declares
``reuse_fresh_outputs``, so a re-run on unchanged inputs returns the sound
design already in the graph instead of writing an equivalent one (nw#203).

The call, end to end:

- ``plan()`` is pure data: one :class:`falaw.CallPlan` (``backend="foley"``,
  ``application="foley.score"``, ``output_kind="json"``) whose ``arguments``
  are what ``foley.score`` is given, with the narration audio named by its
  **project-relative path and its sha256** (hashed at plan time — reading an
  input is allowed). Both enter falaw's cache key, so changed bytes or a moved
  file is a miss. ``estimated_cost_usd`` is ``None``: foley may spend (an LLM
  rung, a generation fallback) and reports no spend, so the cost is unknown,
  never $0. A config's ``max_usd`` / ``allow_generate`` (nw#204) ride in the
  arguments only when set away from foley's defaults, where a gate can read
  the cap. A call already in falaw's cache is planned as a ``"hit"``.
- The executor resolves the path against the project being executed (bound by
  :meth:`NarrationToSoundDesign.execute`, the way a secret is bound: a context
  variable, so falaw's worker threads see it), refuses audio whose bytes no
  longer match the planned sha256, imports foley, runs ``foley.score``, puts
  the FLAC mix into falaw's content store (content-addressed, written
  atomically by :meth:`lacing.ArtifactStore.put_blob`) and returns a JSON
  sidecar: the mix's ``artifact_id`` and ``duration_s``, foley's editable
  timeline, the per-event rationale, credits, SDH captions, the master report
  and notes. Read the mix back with
  ``falaw.content.default_content_store().get_blob(artifact_id)``.
- ``BaseTransform`` turns the sidecar into the annotation body (so
  ``TransformResult.artifacts``, and a fan-out record's ``artifact_ids``, name
  the JSON sidecar; the mix is the body's ``artifact_id``, also in provenance
  of anything derived from it);
  :meth:`~NarrationToSoundDesign._complete_annotation` validates it as
  ``sound-design/v1``.
- ``enabled=False`` plans no call and no skeleton: nothing runs, nothing is
  spent, foley is never imported.
- foley is the ``nw[sound]`` extra, imported inside the executor only; without
  it, the call fails with :class:`nw._extras.MissingExtra` (an ``ImportError``)
  naming ``nw[sound]``. Registering the Transform or the executor, and
  ``import nw``, never load it.

**Hosts with their own narration schema** subclass with their own
``input_kinds`` (the config stays the second kind) and override
:meth:`~NarrationToSoundDesign.narration_track` — ``(project, narration) ->``
:class:`NarrationTrack` — when what foley needs is read from the project (a
host whose spoken text lives on other nodes than the narration's own body;
nw#221). Its default reads the narration body through the three finer seams,
:meth:`~NarrationToSoundDesign.narration_segments`,
:meth:`~NarrationToSoundDesign.narration_audio_path` and
:meth:`~NarrationToSoundDesign.narration_segment_starts`, so a host overriding
those keeps working unchanged.
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from pathlib import Path, PurePath
from typing import Optional
from uuid import uuid4

from falaw import CallPlan, Plan
from falaw.backends import backends
from falaw.cache import cache_get
from lacing import Annotation, Artifact, hash_file

from nw._extras import is_missing, missing_extra
from nw.bodies.sound_design import (
    DFLT_ALLOW_GENERATE,
    NARRATION_TRACK_BODY_SCHEMA_URI,
    SOUND_DESIGN_BODY_SCHEMA_URI,
    SOUND_DESIGN_CONFIG_BODY_SCHEMA_URI,
    SOUND_DESIGN_TIER,
    NarrationTrackBodyV1,
    SoundDesignBodyV1,
    SoundDesignConfigBodyV1,
)
from nw.transforms import (
    BaseTransform,
    OnFailure,
    TransformInputs,
    TransformResult,
    register_transform,
    stamp_transform_identity,
)
from nw.transforms._provenance import derive_provenance

NAME = "narration_to_sound_design.foley"
SOUND_EXTRA = "sound"
FOLEY_PACKAGE = "foley"

SOUND_DESIGN_TOOL = "sound_design"
SOUND_DESIGN_APPLICATION = "foley.score"
SOUND_DESIGN_BACKEND = "foley"
"""The falaw backend this module registers an in-process executor for."""

AUDIO_FORMAT = "flac"
"""The mix's container (foley's lossless archive format)."""

SOUND_DESIGN_TAGS = (
    "rights:licence-gate-fail-closed",
    "rights:intent-commercial-by-default",
    "cost:unknown",
)
"""Registry tags: foley refuses a sound whose licence does not fit the intent;
the intent is the config's ``commercial_ok`` (default: commercial publishing);
and what a run spends is not known in advance."""

_PROJECT_ROOT: ContextVar[Optional[Path]] = ContextVar(
    "nw_sound_design_project_root", default=None
)


@contextmanager
def _relative_to(root) -> Iterator[None]:
    """Resolve the executor's project-relative audio paths against ``root``."""
    token = _PROJECT_ROOT.set(Path(root))
    try:
        yield
    finally:
        _PROJECT_ROOT.reset(token)


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


def _jsonable(value):
    """``json.dumps`` fallback for foley's numeric types (numpy scalars, arrays)."""
    for attr in ("tolist", "item"):
        if hasattr(value, attr):
            return getattr(value, attr)()
    raise TypeError(f"not JSON-serializable: {type(value).__name__}")


def _spend_kwargs(foley, arguments: Mapping) -> dict:
    """``foley.score``'s spend knobs, from the call's arguments (nw#204): absent
    means foley's default, so a plan made before them runs unchanged."""
    kwargs = {}
    if arguments.get("max_usd") is not None:
        kwargs["budget"] = foley.Budget(max_usd=arguments["max_usd"])
    if "allow_generate" in arguments:
        kwargs["allow_generate"] = arguments["allow_generate"]
    return kwargs


def foley_executor(application: str, arguments: Mapping, *, on_event=None) -> dict:
    """The ``backend="foley"`` executor: run ``foley.score``, return the sidecar.

    falaw's :data:`~falaw.backends.BackendExecutor` contract: ``(application,
    arguments) -> raw response``. The raw response is ``{"output": <JSON
    sidecar>}``, which falaw's converter materializes as a ``json`` artifact.
    """
    root = _PROJECT_ROOT.get()
    if root is None:
        raise RuntimeError(
            f"{application}: the narration audio path is project-relative, and "
            "no project is bound. Run this plan through "
            f"nw.get_transform({NAME!r}).execute(project, plan, skeleton)."
        )
    audio = root / arguments["audio"]["path"]
    if hash_file(audio) != arguments["audio"]["sha256"]:
        raise ValueError(
            f"{application}: {audio} changed since the plan was made "
            "(its sha256 no longer matches); plan again."
        )
    foley = _import_foley()
    scored = foley.score(
        list(arguments["segments"]),
        audio=str(audio),
        segment_starts=arguments["segment_starts"],
        commercial_ok=arguments["commercial_ok"],
        max_events=arguments["max_events"],
        master=arguments["master"],
        **_spend_kwargs(foley, arguments),
    )
    woven = scored.weave
    if woven is None:
        raise RuntimeError(f"{application}: foley.score returned no mix for {audio}.")
    from falaw.content import default_content_store

    mix = io.BytesIO()
    foley.audio.save(woven.audio, woven.sr, mix, fmt=AUDIO_FORMAT)
    sidecar = {
        "artifact_id": default_content_store().put_blob(mix.getvalue()),
        "duration_s": len(woven.audio) / woven.sr,
        "timeline": scored.timeline.to_dict(),
        "events": [e.to_dict() for e in scored.events],
        "credits": woven.credits.to_dict(),
        "captions_vtt": woven.captions_vtt,
        "master_report": dict(woven.master_report),
        "notes": [str(n) for n in woven.notes],
    }
    return {"output": json.dumps(sidecar, default=_jsonable)}


def _spend_arguments(config: SoundDesignConfigBodyV1) -> dict:
    """The config's spend knobs, only where they differ from foley's defaults:
    a key absent from the arguments is absent from falaw's cache key, so a
    design made before nw#204 stays a cache hit."""
    arguments = {}
    if config.max_usd is not None:
        arguments["max_usd"] = config.max_usd
    if config.allow_generate != DFLT_ALLOW_GENERATE:
        arguments["allow_generate"] = config.allow_generate
    return arguments


@dataclass(frozen=True)
class NarrationTrack:
    """What foley needs from one narration: its spoken text, its audio, and
    where each sentence starts.

    ``audio_path`` is relative to ``project.root`` (an absolute path also
    works, but pins the plan and its cache key to this machine's layout).
    ``segment_starts`` is ``None`` to let foley align the file.
    """

    segments: list[str]
    audio_path: PurePath
    segment_starts: Optional[list[float]] = None


class NarrationToSoundDesign(BaseTransform):
    """``narration-track/v1`` + ``sound-design-config/v1`` → ``sound-design/v1``."""

    name = NAME
    input_kinds = (NARRATION_TRACK_BODY_SCHEMA_URI, SOUND_DESIGN_CONFIG_BODY_SCHEMA_URI)
    output_kind = SOUND_DESIGN_BODY_SCHEMA_URI
    generate_when = "static"  # one sound design per narration track
    # A re-run on unchanged inputs is a falaw cache hit that completes to the
    # same body: return the sound design already in the graph rather than a
    # second, equivalent node (nw#203).
    reuse_fresh_outputs = True
    attributed_to = f"agent:{NAME}"

    # --- host seams: how a narration node yields what foley needs -------------

    def narration_track(self, project, narration: Annotation) -> NarrationTrack:
        """Everything foley needs from ``narration``, read with the project.

        The seam :meth:`plan` calls (nw#221). Override it when the text or its
        timing lives elsewhere in the project, and compute it once here. The
        default assembles the three finer seams below, which read only the
        narration body.
        """
        return NarrationTrack(
            segments=self.narration_segments(narration),
            audio_path=self.narration_audio_path(project, narration),
            segment_starts=self.narration_segment_starts(narration),
        )

    def narration_segments(self, narration: Annotation) -> list[str]:
        """Sentence-level narration text, in render order."""
        return list(NarrationTrackBodyV1.model_validate(narration.body).segments)

    def narration_audio_path(self, project, narration: Annotation) -> PurePath:
        """The narration audio file, relative to ``project.root``.

        An absolute path also works, but pins the plan (and its cache key) to
        this machine's layout.
        """
        return PurePath(NarrationTrackBodyV1.model_validate(narration.body).audio_path)

    def narration_segment_starts(self, narration: Annotation) -> Optional[list[float]]:
        """Each segment's start in the audio (seconds), or ``None`` to align the file."""
        return NarrationTrackBodyV1.model_validate(narration.body).segment_starts

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

    # --- plan: pure data -------------------------------------------------------

    def plan(
        self, project, inputs: TransformInputs, *, params=None
    ) -> tuple[Plan, tuple[Annotation, ...]]:
        if len(inputs.primary) != 1:
            raise ValueError(
                f"{self.name}: expected exactly one {self.input_kinds[0]} "
                f"annotation in inputs.primary, got {len(inputs.primary)}."
            )
        (narration,) = inputs.primary
        config = self.config(inputs)
        if not config.enabled:
            return Plan(calls=()), ()
        track = self.narration_track(project, narration)
        audio = PurePath(track.audio_path)
        sha = hash_file(Path(project.root) / audio)
        declared = (
            narration.body.get("artifact_id")
            if isinstance(narration.body, Mapping)
            else None
        )
        if declared and declared != sha:
            raise ValueError(
                f"{self.name}: the narration names artifact {declared} but its "
                f"audio file {audio} holds {sha}; provenance would name bytes "
                "that were never used."
            )
        call = CallPlan(
            tool=SOUND_DESIGN_TOOL,
            application=SOUND_DESIGN_APPLICATION,
            backend=SOUND_DESIGN_BACKEND,
            arguments={
                "segments": list(track.segments),
                "audio": {
                    "path": audio.as_posix(),
                    "sha256": sha,
                },
                "segment_starts": (
                    None if track.segment_starts is None else list(track.segment_starts)
                ),
                "commercial_ok": config.commercial_ok,
                "max_events": config.max_events,
                "master": config.master,
                **_spend_arguments(config),
            },
            output_kind="json",
            estimated_cost_usd=None,  # unknown, never free
            metadata={
                "narration_id": str(narration.id),
                "attributed_to": self.attributed_to,
            },
        )
        (call,) = stamp_transform_identity(Plan(calls=(call,)), self).calls
        if cache_get(
            call.application,
            call.arguments,
            backend=call.backend,
            key_extra=call.key_extra or None,
        ):
            call = replace(call, cache_status="hit")
        context = {self.input_kinds[1]: inputs.context[self.input_kinds[1]]}
        skeleton = Annotation(
            id=uuid4(),
            tier=SOUND_DESIGN_TIER,
            reference=narration.reference,
            body=SoundDesignBodyV1().model_dump(),
            body_schema_uri=self.output_kind,
            provenance=derive_provenance(
                self,
                TransformInputs(primary=(narration,), context=context),
                attributed_to=self.attributed_to,
                asset_refs=(sha,),  # the audio actually scored, declared or not
            ),
        )
        return Plan(calls=(call,)), (skeleton,)

    # --- execute: BaseTransform's, with the project bound for the executor ----

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
        with _relative_to(project.root):
            return super().execute(
                project,
                plan,
                skeleton,
                use_cache=use_cache,
                force=force,
                on_failure=on_failure,
                unit_instance_id=unit_instance_id,
                secrets=secrets,
            )

    def _complete_annotation(
        self, skeleton: Annotation, artifact: Artifact
    ) -> Annotation:
        """The sidecar merged into the skeleton, validated as ``sound-design/v1``.

        Refuses a sidecar whose mix is no longer in falaw's content store (a
        size-bounded prune can evict the FLAC and keep the small cached
        sidecar), rather than report a dangling ``artifact_id`` as success."""
        from falaw.content import default_content_store

        merged = super()._complete_annotation(skeleton, artifact)
        body = SoundDesignBodyV1.model_validate(merged.body).model_dump(mode="json")
        if not default_content_store().has_blob(body["artifact_id"]):
            raise RuntimeError(
                f"{self.name}: the cached mix {body['artifact_id']} is gone from "
                "falaw's content store; execute with force=True to make it again."
            )
        return merged.model_copy(update={"body": body})


def _register_executor() -> None:
    """Register :func:`foley_executor` for ``backend="foley"``: replace an
    earlier copy of it (a module reload, whose old executor would read a stale
    context variable), refuse anyone else's."""
    current = (
        backends.get(SOUND_DESIGN_BACKEND) if SOUND_DESIGN_BACKEND in backends else None
    )
    if current is not None and (
        getattr(current, "__module__", None),
        getattr(current, "__qualname__", None),
    ) != (__name__, foley_executor.__qualname__):
        raise RuntimeError(
            f"falaw backend {SOUND_DESIGN_BACKEND!r} is already registered to "
            f"{current!r}; {NAME!r} needs its own executor there."
        )
    if current is not None:
        backends.pop(SOUND_DESIGN_BACKEND)
    backends.register(SOUND_DESIGN_BACKEND, foley_executor)


_register_executor()
register_transform(NAME, NarrationToSoundDesign(), tags=SOUND_DESIGN_TAGS)
