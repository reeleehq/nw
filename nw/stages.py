"""Stages: the plain-English steps of a kind of production, owned by the engine (reelee#458).

A *stage* is a fact about a **kind of production** (short film, music video,
podcast), not about a screen: "Make the reference images" is several transforms, and
a person means the whole. Before this module the stage list existed only as display
text in an app, so "Step 3 of 6", the stage list and the banner total could disagree
and none of them was real.

One source, three derived facts, each with a single owner:

- **Declaration** — :class:`Stage`, on :attr:`nw.Genre.stages` (pure data: a
  plain-English ``name``, whether it is ``free``, and the ``transform_names`` /
  ``body_schema_uris`` that carry it out or evidence it).
- **State** — :func:`stage_states`, *derived from the graph and never stored*:
  ``not_started`` (nothing produced), ``in_progress`` (something produced but stale,
  or a job for one of its transforms is running), ``done`` (produced, none stale), or
  ``unknown`` (the stage names nothing the graph could show, so we do not guess).
  Staleness is :func:`nw.freshness.stale_verdicts_all`'s; the rule is not restated.
  The graph cannot say how many outputs a stage *should* have (how many shots), so
  ``done`` means "has output and none of it is out of date", and the app can pass
  ``active_transforms`` to say a stage is mid-run.
- **Price** — :func:`stage_prices`, composed **at ask time** from a caller-supplied
  ``quote`` (the app builds the plan; :func:`nw.current_quote` re-prices it, the
  nw#74 rule). A free stage is ``0.0`` because it was *declared* free; a stage
  nobody can quote is ``None`` — **unknown, never free**.

:func:`stage_overview` is the one JSON-able answer every surface reads, so the step
list, "Step N of M" and the banner total cannot disagree. The remaining total is
``None`` when any unfinished paid stage is unknown: a missing total beats a wrong
one (reelee-web#305).

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
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional, Sequence

#: ``not_started`` / ``in_progress`` / ``done`` / ``unknown`` — see the module docstring.
STAGE_STATES = ("not_started", "in_progress", "done", "unknown")


@dataclass(frozen=True)
class Stage:
    """One plain-English step of a genre. Pure data; see the module docstring."""

    slug: str
    name: str
    #: Declared free: it never spends, so its price is ``0.0`` without asking anyone.
    free: bool = False
    #: Transforms that carry the stage out; an output is theirs when its
    #: ``was_generated_by`` is ``transform:<name>@...``.
    transform_names: tuple[str, ...] = ()
    #: Body schemas that evidence the stage when no transform makes it (an idea the
    #: person typed in). Matched on the annotation's ``body_schema_uri``.
    body_schema_uris: tuple[str, ...] = ()
    description: str = ""

    def __post_init__(self) -> None:
        for _name in ("transform_names", "body_schema_uris"):
            if not isinstance(getattr(self, _name), tuple):
                object.__setattr__(self, _name, tuple(getattr(self, _name)))
        if not isinstance(self.slug, str) or not self.slug.strip():
            raise ValueError("Stage slug must be a non-empty string")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError(f"Stage {self.slug!r}: name must be a non-empty string")

    @property
    def is_derivable(self) -> bool:
        """Whether the graph can show this stage at all."""
        return bool(self.transform_names or self.body_schema_uris)

    def to_dict(self) -> dict:
        return {
            "slug": self.slug,
            "name": self.name,
            "free": self.free,
            "transform_names": list(self.transform_names),
            "body_schema_uris": list(self.body_schema_uris),
            "description": self.description,
        }


def validate_stages(genre_slug: str, stages: Sequence[Stage], known: Iterable[str]) -> None:
    """Raise ``ValueError`` unless ``stages`` are well-formed against the genre's own
    ``known`` transforms/strategies. Called by :class:`nw.Genre`."""
    if not all(isinstance(s, Stage) for s in stages):
        raise ValueError(f"Genre {genre_slug!r}: stages must all be nw.Stage")
    slugs = [s.slug for s in stages]
    if len(slugs) != len(set(slugs)):
        raise ValueError(f"Genre {genre_slug!r}: stage slugs must be unique, got {slugs}")
    known = set(known)
    for s in stages:
        stray = [t for t in s.transform_names if t not in known]
        if stray:
            raise ValueError(
                f"Genre {genre_slug!r}: stage {s.slug!r} names transforms {stray} "
                "that are not among the genre's transform_names or strategy_names"
            )


@dataclass(frozen=True)
class StageState:
    stage: Stage
    state: str
    produced: int = 0
    stale: int = 0

    def to_dict(self) -> dict:
        return {"state": self.state, "produced": self.produced, "stale": self.stale}


def _transform_of(generated_by: Any) -> Optional[str]:
    if not isinstance(generated_by, str) or not generated_by.startswith("transform:"):
        return None
    return generated_by[len("transform:") :].partition("@")[0] or None


def stage_states(
    stages: Sequence[Stage],
    project,
    *,
    active_transforms: Iterable[str] = (),
) -> list[StageState]:
    """Where ``project`` stands in each of ``stages``, read from its graph.

    ``project`` is anything the graph surfaces accept (a path, a storage, a
    ``nw.Project``). ``active_transforms`` are transform names with a job running
    now, which the graph cannot know; a stage that owns one is ``in_progress``.
    """
    from .freshness import stale_verdicts_all
    from .graph import iter_all_annotations

    stages = tuple(stages)
    if not any(s.is_derivable for s in stages):
        return [StageState(s, "unknown") for s in stages]
    stale_ids = {v.annotation.id for v in stale_verdicts_all(project) if v.is_stale}
    produced = {s.slug: 0 for s in stages}
    stale = {s.slug: 0 for s in stages}
    for ann in iter_all_annotations(project):
        name = _transform_of(ann.provenance.was_generated_by)
        for s in stages:
            if (name is not None and name in s.transform_names) or (
                ann.body_schema_uri in s.body_schema_uris
            ):
                produced[s.slug] += 1
                stale[s.slug] += ann.id in stale_ids
    active = set(active_transforms)
    out = []
    for s in stages:
        if not s.is_derivable:
            state = "unknown"
        elif stale[s.slug] or (active & set(s.transform_names)):
            state = "in_progress"
        elif produced[s.slug]:
            state = "done"
        else:
            state = "not_started"
        out.append(StageState(s, state, produced[s.slug], stale[s.slug]))
    return out


@dataclass(frozen=True)
class StagePrice:
    """A stage's price today. ``total_usd is None`` means unknown, never free."""

    total_usd: Optional[float]
    #: ``"free"`` (declared), ``"quoted"``, or ``"unknown"``.
    status: str

    def to_dict(self) -> dict:
        return {"usd": self.total_usd, "status": self.status}


def stage_prices(
    stages: Sequence[Stage],
    quote: Optional[Callable[[Stage], Any]] = None,
) -> list[StagePrice]:
    """Compose each stage's price now. ``quote(stage)`` returns USD, an
    :class:`nw.PlanQuote` (its ``total_usd``), or ``None``; no ``quote`` means every
    paid stage is unknown. A raising quoter is unknown too: a price we could not
    work out is not a price."""
    out = []
    for s in stages:
        if s.free:
            out.append(StagePrice(0.0, "free"))
            continue
        try:
            raw = quote(s) if quote is not None else None
        except Exception:
            raw = None
        usd = getattr(raw, "total_usd", raw)
        if isinstance(usd, bool) or not isinstance(usd, (int, float)) or usd != usd:
            out.append(StagePrice(None, "unknown"))
        else:
            out.append(StagePrice(float(usd), "quoted"))
    return out


def stage_overview(
    genre,
    project,
    *,
    quote: Optional[Callable[[Stage], Any]] = None,
    active_transforms: Iterable[str] = (),
) -> dict:
    """The one JSON-able answer: stages with state and price, "Step N of M", and the
    total still to spend. ``genre`` is an :class:`nw.Genre` or its slug.

    ``step`` is the 1-based position of the first stage not ``done`` (``of`` when all
    are). ``remaining_total_usd`` sums the price of every stage not ``done`` and is
    ``None`` when any of them is unknown.
    """
    from .genres import get_genre

    g = get_genre(genre) if isinstance(genre, str) else genre
    states = stage_states(g.stages, project, active_transforms=active_transforms)
    prices = stage_prices(g.stages, quote)
    rows = []
    for st, pr in zip(states, prices):
        rows.append(
            {"slug": st.stage.slug, "name": st.stage.name, "free": st.stage.free}
            | st.to_dict()
            | {"price": pr.to_dict()}
        )
    total = len(rows)
    step = next((i + 1 for i, r in enumerate(rows) if r["state"] != "done"), total)
    todo = [r for r in rows if r["state"] != "done"]
    unknown = any(r["price"]["usd"] is None for r in todo)
    return {
        "genre": g.slug,
        "step": step,
        "of": total,
        "complete": bool(rows) and not todo,
        "stages": rows,
        "remaining_total_usd": None if unknown else sum(r["price"]["usd"] for r in todo),
        "remaining_status": "unknown" if unknown else "quoted",
    }


__all__ = [
    "STAGE_STATES",
    "Stage",
    "StagePrice",
    "StageState",
    "stage_overview",
    "stage_prices",
    "stage_states",
    "validate_stages",
]
