"""Body schemas for sound design over a narration track (nw#190).

Three URIs, the inputs and the output of the ``narration_to_sound_design.foley``
Transform (:mod:`nw.transforms.sound_design`):

- ``annot://schema/narration-track/v1`` — **one** narration audio file (a path
  relative to the project root; absolute and escaping paths are refused) and
  the sentence-level text it speaks, in render order. The minimal shape any genre
  with a voice track can produce; a host with its own narration schema
  (braidio's ``narration-render/v1``) subclasses the Transform and overrides its
  extraction methods instead of converting to this one.
- ``annot://schema/sound-design-config/v1`` — the switch and the knobs:
  ``enabled``, ``max_events`` (per segment), ``master`` (the delivery profile)
  and ``commercial_ok`` (the rights intent). Defaults mirror ``foley.score``'s;
  they are restated here as named constants because registering the Transform
  must not import foley (``nw[sound]`` is an extra). A test pins them against
  foley's signature when foley is installed.
- ``annot://schema/sound-design/v1`` — the result: the produced mix's
  ``artifact_id`` (a FLAC in falaw's content store) and duration, foley's editable timeline (``SoundDesignTimeline.to_dict()``;
  re-render it with ``foley.weave(narration, SoundDesignTimeline.from_dict(...))``
  without re-running selection), the per-event rationale, the credits that must
  be published with the output, SDH captions, the measured master report and
  foley's notes (e.g. "word timings are estimates").

``narration-track/v1`` and ``sound-design/v1`` name their audio under
``artifact_id``; :mod:`nw.transforms.asset_refs` declares both, so a sound
design's provenance carries the narration audio's asset id beside the two
annotation ids.
"""

from __future__ import annotations

from pathlib import PurePosixPath, PureWindowsPath
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from lacing.schema import register_body_schema


NARRATION_TRACK_BODY_SCHEMA_URI = "annot://schema/narration-track/v1"
NARRATION_TRACK_TIER = "narration-track"
SOUND_DESIGN_CONFIG_BODY_SCHEMA_URI = "annot://schema/sound-design-config/v1"
SOUND_DESIGN_CONFIG_TIER = "sound-design-config"
SOUND_DESIGN_BODY_SCHEMA_URI = "annot://schema/sound-design/v1"
SOUND_DESIGN_TIER = "sound-design"

DFLT_MAX_EVENTS = 6
"""foley's density cap per segment (``foley.score(max_events=6)``)."""
DFLT_MASTER = "podcast"
"""foley's delivery profile (``foley.score(master="podcast")``)."""
DFLT_COMMERCIAL_OK = True
"""foley's default rights intent: commercial publishing
(``foley.licensing.DEFAULT_INTENDED_USE``). Stated, not deferred, so the graph
records which intent a mix was licence-checked under."""
DFLT_ALLOW_GENERATE = True
"""foley's default: a sound no library has may be generated (a paid fallback)."""


class NarrationTrackBodyV1(BaseModel):
    """Body of a narration-track annotation: one audio file + its sentences."""

    model_config = {"frozen": True, "extra": "forbid"}

    audio_path: str = Field(
        ...,
        min_length=1,
        description=(
            "The narration audio file foley aligns and weaves into, relative "
            "to the project root (POSIX separators; no ``..``)."
        ),
    )
    artifact_id: Optional[str] = Field(
        None,
        description=(
            "``asset_id`` (bare 64-hex sha256) of the narration audio, when it "
            "is a known artifact. Enters the sound design's provenance."
        ),
    )
    segments: list[str] = Field(
        ...,
        min_length=1,
        description="Sentence-level narration text, in render order.",
    )
    segment_starts: Optional[list[float]] = Field(
        None,
        description=(
            "Each segment's start in the audio, in seconds (one per segment, "
            "non-decreasing). ``None`` lets foley align the whole file."
        ),
    )

    @field_validator("audio_path")
    @classmethod
    def _inside_the_project(cls, value: str) -> str:
        posix, windows = PurePosixPath(value), PureWindowsPath(value)
        if posix.is_absolute() or windows.is_absolute() or windows.drive:
            raise ValueError(
                f"audio_path must be relative to the project root, got {value!r}"
            )
        if ".." in posix.parts or ".." in windows.parts:
            raise ValueError(f"audio_path must not leave the project, got {value!r}")
        return value

    @model_validator(mode="after")
    def _one_start_per_segment(self):
        starts = self.segment_starts
        if starts is not None and len(starts) != len(self.segments):
            raise ValueError(
                f"segment_starts has {len(starts)} entries for "
                f"{len(self.segments)} segments; give one start per segment."
            )
        return self


class SoundDesignConfigBodyV1(BaseModel):
    """Body of a sound-design-config annotation: the switch and the knobs."""

    model_config = {"frozen": True, "extra": "forbid"}

    enabled: bool = Field(
        True,
        description=(
            "``False``: the Transform plans nothing and spends nothing; the "
            "graph does not schedule it."
        ),
    )
    max_events: int = Field(
        DFLT_MAX_EVENTS, ge=1, description="Density cap per segment (restraint)."
    )
    master: str = Field(
        DFLT_MASTER,
        min_length=1,
        description="foley's delivery profile name (``foley.MASTER_PROFILES``).",
    )
    commercial_ok: bool = Field(
        DFLT_COMMERCIAL_OK,
        description=(
            "Rights intent for foley's fail-closed licence gate: ``True`` admits "
            "only commercially licensed sounds; ``False`` also admits "
            "non-commercial ones."
        ),
    )
    max_usd: Optional[float] = Field(
        None,
        ge=0,
        allow_inf_nan=False,
        description=(
            "The run's spend cap in USD, passed to foley as its budget. foley "
            "checks each segment's worst case against what is left and raises "
            "when it does not fit, so a cap below what one segment may spend "
            "fails the render, and one below the run's total can fail a later "
            "segment after earlier ones were paid for (reeleehq/foley#281). "
            "Calls of unknown cost are refused unless foley is told to approve "
            "them, and then they are not counted. ``None``: foley's default "
            "cap (it depends on the LLM). The cost stays *unknown*."
        ),
    )
    allow_generate: bool = Field(
        DFLT_ALLOW_GENERATE,
        description=(
            "``False``: retrieval only, no paid generation fallback (offline or "
            "CI renders)."
        ),
    )


class SoundDesignBodyV1(BaseModel):
    """Body of a sound-design annotation: the mix and everything published with it."""

    model_config = {"frozen": True, "extra": "forbid"}

    artifact_id: Optional[str] = Field(
        None,
        description=(
            "sha256 of the mastered FLAC mix, a blob in falaw's content store "
            "(``falaw.content.default_content_store().get_blob(artifact_id)``). "
            "``None`` in a skeleton; filled by ``execute``."
        ),
    )
    duration_s: float = Field(0.0, ge=0, description="Length of the mix, seconds.")
    timeline: dict = Field(
        default_factory=dict,
        description="foley's editable ``SoundDesignTimeline.to_dict()``.",
    )
    events: list[dict] = Field(
        default_factory=list,
        description="Per-event rationale (``ScoredEvent.to_dict()``), in order.",
    )
    credits: dict = Field(
        default_factory=dict,
        description="The credits manifest; must be published with the output.",
    )
    captions_vtt: str = Field("", description="SDH captions, WebVTT.")
    master_report: dict = Field(
        default_factory=dict,
        description="Measured delivery figures (integrated LUFS, true peak).",
    )
    notes: list[str] = Field(
        default_factory=list,
        description='What to know about how the mix was made ("word timings are estimates").',
    )


register_body_schema(NARRATION_TRACK_BODY_SCHEMA_URI, NarrationTrackBodyV1)
register_body_schema(SOUND_DESIGN_CONFIG_BODY_SCHEMA_URI, SoundDesignConfigBodyV1)
register_body_schema(SOUND_DESIGN_BODY_SCHEMA_URI, SoundDesignBodyV1)
