"""Tests for a user-supplied, fixed-weight portfolio template."""

import datetime as dt

import polars as pl
import pytest

from pipeline.backtest import run_backtest
from strategy.fixed_weight_alpha import FixedWeightAlpha
from tests.test_rebalancing import StaticProvider


def make_alpha(**changes) -> FixedWeightAlpha:
    options = {"weights": {"A": 0.6, "B": 0.4}, "rebalance": "monthly"}
    return FixedWeightAlpha(
        "US", "day", ["A", "B"], "2024-01-03", "2024-04-30",
        **(options | changes),
    )


@pytest.mark.parametrize("weights", [
    {"A": 1.0},
    {"A": 0.8, "B": 0.4},
    {"A": -0.1, "B": 1.0},
    {"A": float("nan"), "B": 0.5},
    {"A": 0.0, "B": 0.0},
])
def test_invalid_target_weights_are_rejected(weights):
    with pytest.raises(ValueError, match="weights"):
        make_alpha(weights=weights)


def test_benchmark_is_fetched_but_never_held():
    alpha = make_alpha(benchmark="SPY")
    alpha.update(pl.DataFrame({"timestamp": [dt.datetime(2024, 1, 3)]}))

    assert alpha.get_tickers() == ["A", "B", "SPY"]
    assert alpha.get_weights() == pytest.approx([0.6, 0.4, 0.0])
    assert alpha.holdings == [(dt.datetime(2024, 1, 3), {"A": 0.6, "B": 0.4})]


def test_monthly_schedule_uses_first_available_bar_and_no_lookahead():
    alpha = make_alpha()
    for day in (2, 3, 4):
        alpha.update(pl.DataFrame({"timestamp": [dt.datetime(2024, 1, day)]}))
    alpha.update(pl.DataFrame({"timestamp": [dt.datetime(2024, 2, 1)]}))
    alpha.update(pl.DataFrame({"timestamp": [dt.datetime(2024, 2, 2)]}))

    assert [stamp.date() for stamp, _ in alpha.holdings] == [
        dt.date(2024, 1, 3), dt.date(2024, 2, 1),
    ]
    assert alpha.warmup_period() == dt.timedelta(0)


def test_quarterly_schedule_skips_intermediate_months():
    alpha = make_alpha(rebalance="quarterly")
    for month in (1, 2, 3, 4):
        alpha.update(pl.DataFrame({"timestamp": [dt.datetime(2024, month, 3)]}))
    assert [stamp.month for stamp, _ in alpha.holdings] == [1, 4]


def test_engine_simulates_fixed_weights_with_costs():
    alpha = FixedWeightAlpha(
        "US", "day", ["A", "B"], "2024-01-02", "2024-02-01",
        weights={"A": 0.5, "B": 0.5},
    )
    result = run_backtest(
        StaticProvider({"A": [10.0, 11.0, 12.0], "B": [10.0, 10.0, 10.0]}),
        alpha, "day", "2024-01-02", "2024-02-01", cost_bps=10,
    )
    assert not result.is_empty()
    assert len(alpha.holdings) == 1
    assert result["overall_growth"][-1] > 1.0
