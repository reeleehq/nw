# Stages — the engine owns the stage list (reelee#458)

Decision (owner, 2026-10-30): the engine owns the plain-English stage list. Declared per genre in nw's registry; state derived from the graph and never stored; price composed at ask time.

## Shape

- `nw.Stage(slug, name, free, transform_names, body_schema_uris, description)` is pure data on `nw.Genre.stages`. Validated: unique slugs, transforms must be among the genre's own `transform_names`/`strategy_names`.
- `nw.stage_states(stages, project, active_transforms=())` derives `not_started | in_progress | done | unknown` from annotations: an output is a stage's when `was_generated_by` is `transform:<name>@…` for one of its transforms, or its `body_schema_uri` is one the stage lists (an idea typed in has no transform). `in_progress` = some output is stale (`stale_verdicts_all`) or the app says a job for its transforms is running. `unknown` = the stage names nothing the graph could show; we do not guess.
- `nw.stage_prices(stages, quote)` — `quote(stage)` is the app's (it builds the plan; `nw.current_quote` re-prices it). Free stages are `0.0` because they were declared free. No quoter, a raising quoter, NaN, `None`: **unknown, never free**.
- `nw.stage_overview(genre, project, quote=…)` is the single JSON answer: stages with state and price, `step`/`of`, and `remaining_total_usd` (sum of unfinished stages; `None` if any is unknown). The studio's step list, "Step N of M" and the banner read only this.

## Why not the alternatives

- *Stage state stored on the project*: a second copy of what the graph already says; it drifts. Rejected.
- *Stages per transform*: finer than what a person means; "reference images" is several transforms. Rejected.
- *Done = expected count reached*: the graph cannot know how many shots a project should have. `done` means "has output, none of it out of date"; the app can pass `active_transforms` for mid-run.
- *Quote inside nw*: nw cannot build an app's plans (invariant: nothing above `falaw.Plan` knows the backend). The seam is the `quote` callable.

## Open

Only the short film (narrative_video) is drawn; other genres declare `stages=()` until someone draws them. A genre with no stages answers an empty list, not a guessed one.
