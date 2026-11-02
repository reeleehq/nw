"""``nw.transforms.total_cost``: the one rule for totalling several runs' costs (nw#189)."""

from __future__ import annotations

from nw.transforms import CostTotal, TransformResult, total_cost


def _result(cost=0.0, saved=0.0, unknown=False) -> TransformResult:
    return TransformResult(
        annotations=(),
        cost_usd_actual=cost,
        cache_hit_savings_usd=saved,
        has_unknown_costs=unknown,
    )


def test_sums_are_floats_even_with_nothing_to_sum():
    total = total_cost([])
    assert total == CostTotal(0.0, 0.0, False)
    assert type(total.cost_usd_actual) is float
    assert type(total.cache_hit_savings_usd) is float


def test_it_sums_transform_results_and_ors_unknown():
    total = total_cost([_result(0.5, 0.1), _result(0.25, 0.0, unknown=True)])
    assert total == CostTotal(0.75, 0.1, True)


def test_a_failed_step_marks_the_total_unknown_without_changing_the_sums():
    """What the failed step spent is not in the results: a lower bound, never free."""
    assert total_cost([_result(0.5)], failed=True) == CostTotal(0.5, 0.0, True)


def test_totals_compose_and_a_generator_is_read_once():
    stage = total_cost(_result(1.0, 0.5) for _ in range(2))
    assert stage == CostTotal(2.0, 1.0, False)
    assert total_cost([stage, _result(1.0, unknown=True)]) == CostTotal(3.0, 1.0, True)
