"""The one rule for totalling what several Transform runs cost (nw#189).

A run of many Transforms (a fan-out's units, a host's multi-stage pipeline)
reports one total. Summing the three cost fields by hand in each place is how
two copies of the same rule drift, so they all call :func:`total_cost`:

- ``cost_usd_actual`` and ``cache_hit_savings_usd`` are float sums (``0.0``
  for no results, never the integer ``0``);
- ``has_unknown_costs`` is true when any result says so, when a total is not
  a finite number (a NaN or infinity is no reading of what was spent), **or**
  when the caller says something ``failed``: a step that raised may have been
  billed for calls its discarded result would have carried, so the total is
  then a lower bound, never a reading of "free".

Anything with those three attributes totals, a :class:`CostTotal` included, so
totals compose:

>>> from types import SimpleNamespace as R
>>> a = total_cost([R(cost_usd_actual=0.5, cache_hit_savings_usd=0.1, has_unknown_costs=False)])
>>> total_cost([a, a])
CostTotal(cost_usd_actual=1.0, cache_hit_savings_usd=0.2, has_unknown_costs=False)
>>> total_cost([], failed=True)
CostTotal(cost_usd_actual=0.0, cache_hit_savings_usd=0.0, has_unknown_costs=True)
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol


class Costed(Protocol):
    """What :func:`total_cost` reads: a ``TransformResult``, or a ``CostTotal``."""

    cost_usd_actual: float
    cache_hit_savings_usd: float
    has_unknown_costs: bool


@dataclass(frozen=True, slots=True)
class CostTotal:
    """The cost of several runs, read as :class:`~nw.transforms.TransformResult`'s
    three cost fields are (whose caveats it inherits: ``cost_usd_actual`` is a
    lower bound when anything failed)."""

    cost_usd_actual: float = 0.0
    cache_hit_savings_usd: float = 0.0
    has_unknown_costs: bool = False


def total_cost(results: Iterable[Costed], *, failed: bool = False) -> CostTotal:
    """Total ``results``' costs; ``failed`` says a step outside them raised.

    ``failed=True`` marks the total unknown (a lower bound) without changing
    the sums: what the failed step spent is not in ``results``.
    """
    results = tuple(results)
    cost = sum((r.cost_usd_actual for r in results), 0.0)
    saved = sum((r.cache_hit_savings_usd for r in results), 0.0)
    return CostTotal(
        cost_usd_actual=cost,
        cache_hit_savings_usd=saved,
        has_unknown_costs=failed
        or not (math.isfinite(cost) and math.isfinite(saved))
        or any(r.has_unknown_costs for r in results),
    )
