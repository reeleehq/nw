"""Body schemas for nw's project-graph annotations.

Importing this package registers the schemas with lacing so any annotation
with a matching ``body_schema_uri`` validates correctly. The schemas are:

- ``annot://schema/section/v1``        — timeline section (verse, scene-1, …)
- ``annot://schema/shot/v1``           — renderable visual unit
- ``annot://schema/character-ref/v1``  — pointer to a character folder
- ``annot://schema/environment-ref/v1`` — pointer to an environment folder
- ``annot://schema/decision/v1``       — provenance-rich decision log entry
- ``annot://schema/render-result/v1``  — output of a render Transform
- ``annot://schema/verifying-trace/v1`` — upstream value digests, for early cutoff
- ``annot://schema/unproduced-output/v1`` — why a planned output was never
  produced (nw#44), retired by a later successful retry
- ``annot://schema/genre-envelope/v1`` — the resolved {genre, template, params}
  the project was created as (singleton per project)
- ``annot://schema/narration-track/v1``, ``annot://schema/sound-design-config/v1``,
  ``annot://schema/sound-design/v1`` — the inputs and output of the
  ``narration_to_sound_design.foley`` Transform (nw#190)

These are deliberately small and project-agnostic. Reelee will be able to
walk the same graph for freshness analysis ("what's downstream of this
character description?") without bespoke storage.
"""

from .character_ref import CHARACTER_REF_BODY_SCHEMA_URI, CharacterRefBodyV1
from .decision import DECISION_BODY_SCHEMA_URI, DecisionBodyV1
from .environment_ref import ENVIRONMENT_REF_BODY_SCHEMA_URI, EnvironmentRefBodyV1
from .genre_envelope import (
    GENRE_ENVELOPE_BODY_SCHEMA_URI,
    GENRE_ENVELOPE_TIER,
    GenreEnvelopeBodyV1,
)
from .render_result import (
    RENDER_RESULT_BODY_SCHEMA_URI,
    RENDER_RESULT_TIER,
    RenderResultBodyV1,
)
from .section import SECTION_BODY_SCHEMA_URI, SectionBodyV1
from .shot import SHOT_BODY_SCHEMA_URI, ShotBodyV1
from .sound_design import (
    NARRATION_TRACK_BODY_SCHEMA_URI,
    NARRATION_TRACK_TIER,
    SOUND_DESIGN_BODY_SCHEMA_URI,
    SOUND_DESIGN_CONFIG_BODY_SCHEMA_URI,
    SOUND_DESIGN_CONFIG_TIER,
    SOUND_DESIGN_TIER,
    NarrationTrackBodyV1,
    SoundDesignBodyV1,
    SoundDesignConfigBodyV1,
)
from .unproduced_output import (
    UNPRODUCED_OUTPUT_BODY_SCHEMA_URI,
    UNPRODUCED_OUTPUT_TIER,
    UnproducedOutputBodyV1,
)
from .verifying_trace import (
    VERIFYING_TRACE_BODY_SCHEMA_URI,
    VERIFYING_TRACE_TIER,
    UpstreamDigestV1,
    VerifyingTraceBodyV1,
    build_verifying_trace,
)


__all__ = [
    "CHARACTER_REF_BODY_SCHEMA_URI",
    "CharacterRefBodyV1",
    "DECISION_BODY_SCHEMA_URI",
    "DecisionBodyV1",
    "ENVIRONMENT_REF_BODY_SCHEMA_URI",
    "EnvironmentRefBodyV1",
    "GENRE_ENVELOPE_BODY_SCHEMA_URI",
    "GENRE_ENVELOPE_TIER",
    "GenreEnvelopeBodyV1",
    "RENDER_RESULT_BODY_SCHEMA_URI",
    "RENDER_RESULT_TIER",
    "RenderResultBodyV1",
    "SECTION_BODY_SCHEMA_URI",
    "SectionBodyV1",
    "SHOT_BODY_SCHEMA_URI",
    "ShotBodyV1",
    "NARRATION_TRACK_BODY_SCHEMA_URI",
    "NARRATION_TRACK_TIER",
    "NarrationTrackBodyV1",
    "SOUND_DESIGN_CONFIG_BODY_SCHEMA_URI",
    "SOUND_DESIGN_CONFIG_TIER",
    "SoundDesignConfigBodyV1",
    "SOUND_DESIGN_BODY_SCHEMA_URI",
    "SOUND_DESIGN_TIER",
    "SoundDesignBodyV1",
    "UNPRODUCED_OUTPUT_BODY_SCHEMA_URI",
    "UNPRODUCED_OUTPUT_TIER",
    "UnproducedOutputBodyV1",
    "VERIFYING_TRACE_BODY_SCHEMA_URI",
    "VERIFYING_TRACE_TIER",
    "UpstreamDigestV1",
    "VerifyingTraceBodyV1",
    "build_verifying_trace",
]
