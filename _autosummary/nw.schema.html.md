# nw.schema

Schema for an nw project — narrative-workflow SSOT data shapes.

A project is a folder with a `project.json` at its root. The shape is
deliberately compatible with the layout muvid established for music-video
projects, so the_bells_v\* fixtures load directly into nw without
migration. nw generalizes muvid’s IR by:

- making `RenderStrategy` open (a string), so apps can register
  their own strategies (composite_lipsync, slideshow, panel, …) without
  touching nw,
- adding [`ProjectSummary`](#nw.schema.ProjectSummary) as a typed read view returned by
  `Project.read_summary()`,
- promoting setters that muvid expressed via `python -c` glue
  (`set_title`, `set_global_style`, `set_character_anchor`).

Pydantic is used (instead of frozen dataclasses) for two reasons:

1. lacing already uses Pydantic — sharing the conventions keeps the
   ecosystem coherent.
2. nw will eventually round-trip schemas through HTTP/MCP; Pydantic gives
   JSON-Schema export and validation for free.

### Classes

| [`CharacterRef`](#nw.schema.CharacterRef)(\*, name[, description, ...])        | Pointer to a character folder under `characters/<name>/`.                                                                                               |
|----------------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------------------------------------------------------------|
| [`DecisionEntry`](#nw.schema.DecisionEntry)(\*, kind[, at, payload])            | One entry of a project's decision log, flattened for display.                                                                                           |
| [`EnvironmentRef`](#nw.schema.EnvironmentRef)(\*, name[, description, ...])      | Pointer to an environment folder under `environments/<name>/`.                                                                                          |
| [`ProjectSpec`](#nw.schema.ProjectSpec)(\*[, schema_version, title, ...])     | The top-level project SSOT, persisted as `project.json`.                                                                                                |
| [`ProjectSummary`](#nw.schema.ProjectSummary)(\*, title, root, ...)              | Typed read view of a project — what `muvid status` printed, but typed.                                                                                  |
| [`ResumptionBrief`](#nw.schema.ResumptionBrief)(\*, title, root[, ...])           | A "where we left off" snapshot, returned by [`nw.Project.resumption_brief()`](nw.html.md#nw.Project.resumption_brief). |
| [`SectionSpec`](#nw.schema.SectionSpec)(\*, id, start_s, end_s[, label, ...]) | A non-overlapping span of the project's master timeline.                                                                                                |
| [`ShotSpec`](#nw.schema.ShotSpec)(\*, id, start_s, end_s[, ...])           | A timeline-locked visual unit.                                                                                                                          |
| [`SongInfo`](#nw.schema.SongInfo)(\*, audio_path, duration_s[, ...])       | Metadata for the master audio file.                                                                                                                     |

### *class* nw.schema.CharacterRef(, name, description='', reference_image_urls=(), costume='', age='', default_setting='', distinguishing_features=(), palette_anchors=(), do_not_do=())

Bases: `BaseModel`

Pointer to a character folder under `characters/<name>/`.

The stable-attribute fields mirror
[`nw.bodies.CharacterRefBodyV1`](nw.bodies.html.md#nw.bodies.CharacterRefBodyV1) field-for-field, and that is
load-bearing rather than cosmetic: [`nw.Project.read_spec()`](nw.html.md#nw.Project.read_spec) builds
a `CharacterRef` from the graph body and
[`nw.Project.write_spec()`](nw.html.md#nw.Project.write_spec) writes the body back from the
`CharacterRef`. Any field present on the body but missing here is
**silently erased** by the next `update_spec` — which is what used to
happen to `reference_image_urls`. Add a field to one, add it to both.

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'ignore'}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

### *class* nw.schema.DecisionEntry(\*, kind, at=None, payload=<factory>)

Bases: `BaseModel`

One entry of a project’s decision log, flattened for display.

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'ignore'}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

### *class* nw.schema.EnvironmentRef(, name, description='', reference_image_urls=())

Bases: `BaseModel`

Pointer to an environment folder under `environments/<name>/`.

Mirrors [`nw.bodies.EnvironmentRefBodyV1`](nw.bodies.html.md#nw.bodies.EnvironmentRefBodyV1) field-for-field, for the
same load-bearing reason as [`CharacterRef`](#nw.schema.CharacterRef) — see that docstring.
`reference_image_urls` (the lookbook the FE curates for a *location*)
was erased by every `update_spec` until this mirror was completed.

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'ignore'}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

### *class* nw.schema.ProjectSpec(, schema_version=1, title='', song=None, characters=(), environments=(), sections=(), shots=(), global_style='', notes='')

Bases: `BaseModel`

The top-level project SSOT, persisted as `project.json`.

Field names and order are chosen to round-trip identically with muvid’s
ProjectSpec for `schema_version=1`, so the_bells_v\* fixtures (and any
other muvid-shaped project) load and re-save without churn.

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'ignore'}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

### *class* nw.schema.ProjectSummary(, title, root, schema_version, song_path, song_duration_s, character_count, environment_count, section_count, shot_count, rendered_shot_count, has_lyrics, has_alignment, has_script, has_final_compose)

Bases: `BaseModel`

Typed read view of a project — what `muvid status` printed, but typed.

Returned by `Project.read_summary()`. Holds the small facts the user
most often wants: title, root, song path, counts of characters / shots /
sections / output, plus a coarse “stages_done” list naming the lifecycle
stages that have been reached.

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'ignore'}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

#### *property* stages_done *: [list](https://docs.python.org/3/builtins/stdtypes.html#list)[[str](https://docs.python.org/3/builtins/stdtypes.html#str)]*

Coarse stage list — what’s been reached, in lifecycle order.

### *class* nw.schema.ResumptionBrief(\*, title, root, last_session_at=None, gap_seconds=None, recent_decisions=(), downstream_of_last_authored_change=<factory>, last_authored_change_id=None, total_spend_usd=0.0, unrendered_shot_ids=(), suggested_next=<factory>, caveats=<factory>)

Bases: `BaseModel`

A “where we left off” snapshot, returned by [`nw.Project.resumption_brief()`](nw.html.md#nw.Project.resumption_brief).

Pure data: no fal calls, no LLM, no network. reelee renders it as prose
and injects it as the first tool-result of a session.

\*\*The field names are chosen to be honest about what nw can currently
measure\*\*, because a confidently wrong number is worse than no number:

- `downstream_of_last_authored_change` is *not* “stale”. It is
  `nw.descendants_of` — pure provenance reachability, comparing no
  content and no timestamp — so this set includes everything already
  regenerated since the change. It is an **upper bound** on what needs
  attention, and it is named for what it measures.

  `nw.stale_after` is the narrower answer and it now cuts off early
  (nw#24), so switching this field to it would return a smaller and
  correct set. That is deliberately **not** done here: the field would
  then be named for the wrong measurement, and which of the two a
  resumption brief should show is nw#7’s call, not nw#24’s. Callers who
  want the exact set can call `nw.stale_after` with
  `last_authored_change_id`.
- The walk starts at the last **authored** change — the most recent
  annotation the user wrote (a shot, a section, a character or
  environment ref), never one a Transform derived. Walking from “the
  newest annotation” instead would be inverted: the newest node in a
  provenance graph is by construction a *leaf*, so its descendant set is
  empty in exactly the case the field exists for.
- `total_spend_usd` sums *every* recorded render decision across
  every store scope. Nothing records per-branch outcomes yet, so a render
  that failed after being billed is counted here exactly like one that
  succeeded. Also an upper bound.

`caveats` carries those qualifications as data — so a consumer
renders them next to the numbers instead of rediscovering them.

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'ignore'}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

### *class* nw.schema.SectionSpec(, id, start_s, end_s, label='', energy='', mood='')

Bases: `BaseModel`

A non-overlapping span of the project’s master timeline.

`label` is free-form (“intro”, “verse”, “chorus”, “scene-1”, “act-2”,
…) so different apps (music-video, explainer, podcast-clip) can use
their own taxonomy.

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'ignore'}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

### *class* nw.schema.ShotSpec(, id, start_s, end_s, section_id='', render_strategy='image_to_video', environment='', characters=(), description='', camera='', framing='medium', notes='')

Bases: `BaseModel`

A timeline-locked visual unit.

`[start_s, end_s)` is half-open. `render_strategy` is an open string
rather than a closed Literal, so apps can register their own strategies
via [`nw.renderers.register_strategy()`](nw.renderers.html.md#nw.renderers.register_strategy) (Phase 1b.3) without modifying
the schema.

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'ignore'}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].

### *class* nw.schema.SongInfo(, audio_path, duration_s, sample_rate=0, bitrate=0, bpm=None)

Bases: `BaseModel`

Metadata for the master audio file.

Compatible with muvid’s SongInfo by field name and type.

#### model_config *: [ClassVar](https://docs.python.org/3/library/typing.html#typing.ClassVar)[ConfigDict]* *= {'extra': 'ignore'}*

Configuration for the model, should be a dictionary conforming to [`ConfigDict`][pydantic.config.ConfigDict].
