# nw.stages

Stages: the plain-English steps of a kind of production, owned by the engine (reelee#458).

A *stage* is a fact about a **kind of production** (short film, music video,
podcast), not about a screen: “Make the reference images” is several transforms, and
a person means the whole. Before this module the stage list existed only as display
text in an app, so “Step 3 of 6”, the stage list and the banner total could disagree
and none of them was real.

One source, three derived facts, each with a single owner:

- **Declaration** — [`Stage`](#nw.stages.Stage), on [`nw.Genre.stages`](nw.html.md#nw.Genre.stages) (pure data: a
  plain-English `name`, whether it is `free`, and the `transform_names` /
  `body_schema_uris` that carry it out or evidence it).
- **State** — [`stage_states()`](#nw.stages.stage_states), *derived from the graph and never stored*:
  `not_started` (nothing produced), `in_progress` (something produced but stale,
  or a job for one of its transforms is running), `done` (produced, none stale), or
  `unknown` (the stage names nothing the graph could show, so we do not guess).
  Staleness is [`nw.freshness.stale_verdicts_all()`](nw.freshness.html.md#nw.freshness.stale_verdicts_all)’s; the rule is not restated.
  The graph cannot say how many outputs a stage *should* have (how many shots), so
  `done` means “has output and none of it is out of date”, and the app can pass
  `active_transforms` to say a stage is mid-run.
- **Price** — [`stage_prices()`](#nw.stages.stage_prices), composed **at ask time** from a caller-supplied
  `quote` (the app builds the plan; [`nw.current_quote()`](nw.html.md#nw.current_quote) re-prices it, the
  nw#74 rule). A free stage is `0.0` because it was *declared* free; a stage
  nobody can quote is `None` — **unknown, never free**.

[`stage_overview()`](#nw.stages.stage_overview) is the one JSON-able answer every surface reads, so the step
list, “Step N of M” and the banner total cannot disagree. The remaining total is
`None` when any unfinished paid stage is unknown: a missing total beats a wrong
one (reelee-web#305).

```pycon
>>> from nw.genres import Genre
>>> g = Genre(slug="demo_stages", title="Demo", transform_names=("a.t",),
...           stages=(Stage("idea", "The idea", free=True),
...                   Stage("make", "Make it", transform_names=("a.t",))))
>>> [s.name for s in g.stages]
['The idea', 'Make it']
>>> stage_prices(g.stages, lambda s: 1.5)[1].total_usd
1.5
>>> stage_prices(g.stages, lambda s: None)[1].status
'unknown'
```

### Module Attributes

| [`STAGE_STATES`](#nw.stages.STAGE_STATES)   | `not_started` / `in_progress` / `done` / `unknown` — see the module docstring.   |
|-----------------------------------------------------------------|----------------------------------------------------------------------------------|

### Functions

| [`stage_overview`](#nw.stages.stage_overview)(genre, project, \*[, quote, ...])   | The one JSON-able answer: stages with state and price, "Step N of M", and the total still to spend.       |
|-----------------------------------------------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------|
| [`stage_prices`](#nw.stages.stage_prices)(stages[, quote])                      | Compose each stage's price now.                                                                           |
| [`stage_states`](#nw.stages.stage_states)(stages, project, \*[, ...])           | Where `project` stands in each of `stages`, read from its graph.                                          |
| [`validate_stages`](#nw.stages.validate_stages)(genre_slug, stages, known)         | Raise `ValueError` unless `stages` are well-formed against the genre's own `known` transforms/strategies. |

### Classes

| [`Stage`](#nw.stages.Stage)(slug, name[, free, transform_names, ...])   | One plain-English step of a genre.   |
|----------------------------------------------------------------------------------------------------|--------------------------------------|
| [`StagePrice`](#nw.stages.StagePrice)(total_usd, status)                     | A stage's price today.               |
| [`StageState`](#nw.stages.StageState)(stage, state[, produced, stale])       |                                      |

### nw.stages.STAGE_STATES *= ('not_started', 'in_progress', 'done', 'unknown')*

`not_started` / `in_progress` / `done` / `unknown` — see the module docstring.

### *class* nw.stages.Stage(slug, name, free=False, transform_names=(), body_schema_uris=(), description='')

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

One plain-English step of a genre. Pure data; see the module docstring.

#### body_schema_uris *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), ...]* *= ()*

Body schemas that evidence the stage when no transform makes it (an idea the
person typed in). Matched on the annotation’s `body_schema_uri`.

#### free *: [bool](https://docs.python.org/3/builtins/functions.html#bool)* *= False*

it never spends, so its price is `0.0` without asking anyone.

* **Type:**
  Declared free

#### *property* is_derivable *: [bool](https://docs.python.org/3/builtins/functions.html#bool)*

Whether the graph can show this stage at all.

#### transform_names *: [tuple](https://docs.python.org/3/builtins/stdtypes.html#tuple)[[str](https://docs.python.org/3/builtins/stdtypes.html#str), ...]* *= ()*

Transforms that carry the stage out; an output is theirs when its
`was_generated_by` is `transform:<name>@...`.

### *class* nw.stages.StagePrice(total_usd, status)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

A stage’s price today. `total_usd is None` means unknown, never free.

#### status *: [str](https://docs.python.org/3/builtins/stdtypes.html#str)*

`"free"` (declared), `"quoted"`, or `"unknown"`.

### *class* nw.stages.StageState(stage, state, produced=0, stale=0)

Bases: [`object`](https://docs.python.org/3/builtins/functions.html#object)

### nw.stages.stage_overview(genre, project, , quote=None, active_transforms=())

The one JSON-able answer: stages with state and price, “Step N of M”, and the
total still to spend. `genre` is an [`nw.Genre`](nw.html.md#nw.Genre) or its slug.

`step` is the 1-based position of the first stage not `done` (`of` when all
are). `remaining_total_usd` sums the price of every stage not `done` and is
`None` when any of them is unknown.

* **Return type:**
  [`dict`](https://docs.python.org/3/builtins/stdtypes.html#dict)

### nw.stages.stage_prices(stages, quote=None)

Compose each stage’s price now. `quote(stage)` returns USD, an
[`nw.PlanQuote`](nw.html.md#nw.PlanQuote) (its `total_usd`), or `None`; no `quote` means every
paid stage is unknown. A raising quoter is unknown too: a price we could not
work out is not a price.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`StagePrice`](#nw.stages.StagePrice)]

### nw.stages.stage_states(stages, project, , active_transforms=())

Where `project` stands in each of `stages`, read from its graph.

`project` is anything the graph surfaces accept (a path, a storage, a
`nw.Project`). `active_transforms` are transform names with a job running
now, which the graph cannot know; a stage that owns one is `in_progress`.

* **Return type:**
  [`list`](https://docs.python.org/3/builtins/stdtypes.html#list)[[`StageState`](#nw.stages.StageState)]

### nw.stages.validate_stages(genre_slug, stages, known)

Raise `ValueError` unless `stages` are well-formed against the genre’s own
`known` transforms/strategies. Called by [`nw.Genre`](nw.html.md#nw.Genre).

* **Return type:**
  [`None`](https://docs.python.org/3/builtins/constants.html#None)
