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

One run's cost comes from its falaw ``ExecutionReport`` through
:func:`report_cost`, the same rule at the call level: a *failed* call is a
lower bound even when priced, since the vendor may have billed it before it
raised and falaw leaves it out of ``estimated_spend_usd`` (nw#214).

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


def report_cost(report) -> CostTotal:
    """One run's cost, read off its falaw ``ExecutionReport``.

    ``has_unknown_costs`` is the report's (an unpriced call that may have
    billed, falaw#141) **or** any failed call: falaw excludes a failed *priced*
    call from ``estimated_spend_usd`` without flagging it, because it cannot
    know whether the vendor billed — so the sum is then a lower bound (nw#214).
    A blocked call never ran and leaves the figure exact.

    >>> from types import SimpleNamespace as Report
    >>> r = Report(estimated_spend_usd=0.04, cache_hit_savings_usd=0.0,
    ...            has_unknown_costs=False, failed=("call",))
    >>> report_cost(r).has_unknown_costs
    True
    """
    return CostTotal(
        cost_usd_actual=report.estimated_spend_usd,
        cache_hit_savings_usd=report.cache_hit_savings_usd,
        has_unknown_costs=bool(report.has_unknown_costs or report.failed),
    )


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
