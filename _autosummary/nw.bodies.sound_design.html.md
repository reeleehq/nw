# nw.bodies.sound_design

Body schemas for sound design over a narration track (nw#190).

Three URIs, the inputs and the output of the `narration_to_sound_design.foley`
Transform (`nw.transforms.sound_design`):

- `annot://schema/narration-track/v1` — **one** narration audio file (a path
  relative to the project root; absolute and escaping paths are refused) and
  the sentence-level text it speaks, in render order. The minimal shape any genre
  with a voice track can produce; a host with its own narration schema
  (braidio’s `narration-render/v1`) subclasses the Transform and overrides its
  extraction methods instead of converting to this one.
- `annot://schema/sound-design-config/v1` — the switch and the knobs:
  `enabled`, `max_events` (per segment), `master` (the delivery profile)
  and `commercial_ok` (the rights intent). Defaults mirror `foley.score`’s;
  they are restated here as named constants because registering the Transform
  must not import foley (`nw[sound]` is an extra). A test pins them against
  foley’s signature when foley is installed.
- `annot://schema/sound-design/v1` — the result: the produced mix’s
  `artifact_id` (a FLAC in falaw’s content store) and duration, foley’s editable timeline (`SoundDesignTimeline.to_dict()`;
  re-render it with `foley.weave(narration, SoundDesignTimeline.from_dict(...))`
  without re-running selection), the per-event rationale, the credits that must
  be published with the output, SDH captions, the measured master report and
  foley’s notes (e.g. “word timings are estimates”).

`narration-track/v1` and `sound-design/v1` name their audio under
`artifact_id`; `nw.transforms.asset_refs` declares both, so a sound
design’s provenance carries the narration audio’s asset id beside the two
annotation ids.

### Module Attributes

| [`DFLT_MAX_EVENTS`](#nw.bodies.sound_design.DFLT_MAX_EVENTS)     | foley's density cap per segment (`foley.score(max_events=6)`).   |
|----------------------------------------------------------------------|------------------------------------------------------------------|
| [`DFLT_MASTER`](#nw.bodies.sound_design.DFLT_MASTER)         | foley's delivery profile (`foley.score(master="podcast")`).      |
| [`DFLT_COMMERCIAL_OK`](#nw.bodies.sound_design.DFLT_COMMERCIAL_OK)  | commercial publishing (`foley.licensing.DEFAULT_INTENDED_USE`).  |
| [`DFLT_ALLOW_GENERATE`](#nw.bodies.sound_design.DFLT_ALLOW_GENERATE) | a sound no library has may be generated (a paid fallback).       |

### Classes

| [`NarrationTrackBodyV1`](#nw.bodies.sound_design.NarrationTrackBodyV1)(\*, audio_path[, ...])   | Body of a narration-track annotation: one audio file + its sentences.        |
|------------------------------------------------------------------------------------------------|------------------------------------------------------------------------------|
| [`SoundDesignBodyV1`](#nw.bodies.sound_design.SoundDesignBodyV1)(\*[, artifact_id, ...])     | Body of a sound-design annotation: the mix and everything published with it. |
| [`SoundDesignConfigBodyV1`](#nw.bodies.sound_design.SoundDesignConfigBodyV1)(\*[, enabled, ...])   | Body of a sound-design-config annotation: the switch and the knobs.          |

### nw.bodies.sound_design.DFLT_ALLOW_GENERATE *= True*

a sound no library has may be generated (a paid fallback).

* **Type:**
  foley’s default

### nw.bodies.sound_design.DFLT_COMMERCIAL_OK *= True*

commercial publishing
(`foley.licensing.DEFAULT_INTENDED_USE`). Stated, not deferred, so the graph
records which intent a mix was licence-checked under.

* **Type:**
  foley’s default rights intent

### nw.bodies.sound_design.DFLT_MASTER *= 'podcast'*

foley’s delivery profile (`foley.score(master="podcast")`).

### nw.bodies.sound_design.DFLT_MAX_EVENTS *= 6*

foley’s density cap per segment (`foley.score(max_events=6)`).

### *class* nw.bodies.sound_design.NarrationTrackBodyV1(, audio_path, artifact_id=None, segments, segment_starts=None)

Bases: `BaseModel`

Body of a narration-track annotation: one audio file + its sentences.

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'forbid', 'frozen': True}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

### *class* nw.bodies.sound_design.SoundDesignBodyV1(\*, artifact_id=None, duration_s=0.0, timeline=<factory>, events=<factory>, credits=<factory>, captions_vtt='', master_report=<factory>, notes=<factory>)

Bases: `BaseModel`

Body of a sound-design annotation: the mix and everything published with it.

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'forbid', 'frozen': True}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

### *class* nw.bodies.sound_design.SoundDesignConfigBodyV1(, enabled=True, max_events=6, master='podcast', commercial_ok=True, max_usd=None, allow_generate=True)

Bases: `BaseModel`

Body of a sound-design-config annotation: the switch and the knobs.

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'forbid', 'frozen': True}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].
