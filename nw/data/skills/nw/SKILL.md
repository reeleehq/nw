---
name: nw
description: >-
  Use nw (Narrative Workflow), the orchestration substrate of the audiovisual
  (av) production stack: a project is a folder, a genre specializes it, and work
  runs prepare → plan → execute behind a cost gate, with a provenance graph that
  says what is stale. Use when operating on an AV project folder, a "narrative
  workflow", a genre or template (music video, commentary weave, slideshow), a
  Transform, a falaw Plan or its cost quote, "which shots need re-rendering",
  "what is stale", "render this project", freshness, project storage, or
  validating finished AV work. Python: `import nw`.
metadata:
  audience: consumers
---

# nw — Narrative Workflow

The layer where `lacing`'s annotation graph meets `falaw`'s costed execution.
Layering: `lacing → nw → falaw.Plan → backends`. Nothing above `falaw.Plan` may know which backend runs. Apps (`reelee`, `muvid`, `braidio`) build on nw; nw ships **no** genres of its own.

## The model

- **Project** (`nw.Project`): a folder holding a spec, a graph store and assets. Reach project state through a storage (`nw.FolderStorage` by default, `nw.MappingStorage` when the caller owns persistence), never by opening a store by path.
- **Genre / Template**: a reusable definition of a production kind. The owning app registers it (`nw.register_genre`); ask the registry what is live: `nw.list_genres()`, `nw.genre_catalog()`, `nw.resolve_genre(genre, template)`, `nw.get_genre(slug).is_ready()`.
- **Transform**: the swappable, costed "A-annotation → B-annotation" step. `nw.transform_catalog()` is the JSON-able list of what can be run.
- **prepare → plan → execute**: `prepare` is local and free, `plan` is pure data (a `falaw.Plan`, inspect `plan.total_cost_usd`), `execute` is the only phase that spends. Re-quote a stored plan with `nw.current_quote(plan)`: `None` means unknown, never free.
- **Freshness**: `nw.freshness.all_stale(project)` answers "what is stale right now"; `stale_after(project, changed_id)` answers "what did this change invalidate". Only annotations written through `ProjectGraph.add_annotation` carry the trace freshness needs.
- **Validation**: `nw.validation.suggest("...")` finds checks for a request; `validate(...)` runs the ones you place. Nothing runs unless you ask.

## When to use nw vs a substrate package directly

Use nw when the work is a *project* with state that outlives one call: several shots or assets, a spend to gate, re-renders to limit to what changed, or a genre an app already registered. Call a substrate package directly (`falaw` for one priced call, `lacing` for a bare annotation store, `burns`, `tituli` and the like for one media operation) for a one-off with no project and no provenance to keep.

## Rules that are easy to break

1. Plans are pure data: no network, no billing in any `plan()`.
2. Costs: `None` is unknown, not free. Read observed spend, not per-artifact sums.
3. A behaviour change must reach the cache key (`impl_version`), or a stale artifact is served forever.
4. Write derived annotations through `ProjectGraph`, or freshness calls them stale forever.
5. A secret is passed only as `secrets=` (an `nw.Secrets`), never stored in a node, plan, cache key, record or log.
6. Tests never spend: the suite is hermetic.

## Where to read next

The repo's `CLAUDE.md` is the entry point; module docstrings are the specs (`nw/freshness.py`, `nw/transforms/__init__.py`, `nw/transforms/fanout.py`, `nw/storage.py`). The README gives the tour, and `misc/docs/` the design notes (execution semantics, fan-out, validation, why nw is a substrate). For the wider AV stack, read the group's workspace overview if one is on hand.
