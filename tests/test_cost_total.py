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


def test_a_cost_that_is_not_a_number_is_unknown_not_known():
    assert total_cost([_result(float("nan"))]).has_unknown_costs is True
    assert total_cost([_result(0.5, float("inf"))]).has_unknown_costs is True


# --- one run's cost, off falaw's report (nw#214) ---------------------------

from falaw import CallPlan  # noqa: E402
from falaw.outcomes import CallOutcome, ExecutionReport  # noqa: E402

from nw.transforms.costs import report_cost  # noqa: E402


def _call(price):
    return CallPlan(
        tool="t", application="a", arguments={}, output_kind="image",
        estimated_cost_usd=price,
    )


def _report(*outcomes):
    return ExecutionReport(
        outcomes=tuple(
            CallOutcome(
                index=i,
                call=c,
                status=s,
                error=RuntimeError() if s == "failed" else None,
                reason="upstream failed" if s == "blocked" else "",
            )
            for i, (c, s) in enumerate(outcomes)
        )
    )


def test_a_failed_priced_call_makes_the_run_a_lower_bound():
    """falaw leaves a failed priced call out of the sum without flagging it:
    the vendor may have billed it, so the figure is a lower bound (nw#214)."""
    report = _report((_call(0.04), "failed"))
    assert report.has_unknown_costs is False  # falaw's flag alone would read exact
    assert report_cost(report) == CostTotal(0.0, 0.0, True)


def test_a_blocked_call_never_ran_and_leaves_the_figure_exact():
    assert report_cost(_report((_call(0.04), "blocked"))).has_unknown_costs is False


def test_an_unpriced_failed_call_is_unknown_as_falaw_says():
    assert report_cost(_report((_call(None), "failed"))).has_unknown_costs is True
