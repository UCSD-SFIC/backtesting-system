from __future__ import annotations

import datetime as dt

import numpy as np
import polars as pl
import pytest

from pipeline.backtest import run_backtest
from strategy.allocation_alpha import AllocationAlpha
from strategy.signals import cap_weights, high_52_week, momentum, top_n
from tests.test_rebalancing import StaticProvider

# Tests for ranking signals, portfolio construction, and the allocation strategy.

nan = np.nan


def test_momentum_skips_the_most_recent_bars():
    prices = np.array([[10.0, 20.0], [11.0, 19.0], [12.0, 18.0], [15.0, 30.0], [99.0, 1.0]])

    # lookback 3, skip 1: from row -4 to row -2.
    scores = momentum(prices, lookback=3, skip=1)

    assert scores == pytest.approx([15.0 / 11.0 - 1, 30.0 / 19.0 - 1])


def test_momentum_needs_enough_history_and_a_start_price():
    prices = np.array([[nan, 5.0], [2.0, 6.0], [3.0, 7.0]])

    assert np.isnan(momentum(prices, lookback=3, skip=0)).all()
    scores = momentum(prices, lookback=2, skip=0)
    assert np.isnan(scores[0])
    assert scores[1] == pytest.approx(7.0 / 5.0 - 1)


def test_high_52_week_ratio_and_gaps():
    prices = np.array([[10.0, 10.0], [20.0, nan], [15.0, 12.0]])

    scores = high_52_week(prices, window=3)

    assert scores[0] == pytest.approx(0.75)
    assert np.isnan(scores[1])


def test_top_n_ignores_ineligible_and_keeps_ticker_order_on_ties():
    scores = np.array([0.1, nan, 0.5, 0.5, -0.2])

    assert top_n(scores, 3).tolist() == [2, 3, 0]
    assert top_n(np.array([nan, nan]), 2).tolist() == []


def test_cap_weights_redistributes_excess_pro_rata():
    capped = cap_weights(np.array([0.5, 0.3, 0.2]), 0.4)

    assert capped == pytest.approx([0.4, 0.36, 0.24])


def test_cap_weights_leaves_unplaceable_excess_in_cash():
    assert cap_weights(np.array([1.0, 0.0]), 0.25) == pytest.approx([0.25, 0.0])


def make_alpha(tickers, **params) -> AllocationAlpha:
    defaults = {"lookback": 3, "skip": 0, "high_window": 3, "min_price": 0.0}
    return AllocationAlpha("US", "day", tickers, "2024-01-01", "2024-12-31", **(defaults | params))


def test_sleeves_split_capital_between_signals():
    # A has the best momentum; B is at its high but has weak momentum.
    prices = np.array(
        [
            [10.0, 10.0, 10.0],
            [12.0, 8.0, 10.0],
            [16.0, 9.0, 10.0],
            [15.0, 11.0, 10.0],
        ]
    )
    alpha = make_alpha(["A", "B", "C"], sleeves={"momentum": 0.7, "high_52_week": 0.3}, top_n=1)

    assert alpha.target_weights(prices) == pytest.approx([0.7, 0.3, 0.0])


def test_each_sleeve_can_select_a_different_number_of_stocks():
    prices = np.array([[10.0, 10.0, 10.0], [12.0, 8.0, 10.0],
                       [16.0, 9.0, 10.0], [15.0, 11.0, 10.0]])
    alpha = make_alpha(
        ["A", "B", "C"], sleeves={"momentum": 0.3, "high_52_week": 0.7},
        top_n=1, sleeve_top_n={"momentum": 1, "high_52_week": 2},
    )
    assert alpha.target_weights(prices) == pytest.approx([0.3, 0.35, 0.35])


def test_historical_universe_excludes_inactive_stock(tmp_path):
    membership = tmp_path / "members.csv"
    membership.write_text("ticker,start_date,end_date\nA,2020-01-01,2023-12-31\nB,2020-01-01,\n")
    alpha = make_alpha(["A", "B"], sleeves={"momentum": 1.0}, top_n=1,
                       membership_file=str(membership))
    prices = np.array([[10.0, 10.0], [12.0, 10.1], [15.0, 10.2], [20.0, 10.3]])
    assert alpha.target_weights(prices, on_date=dt.date(2024, 1, 2)) == pytest.approx([0, 1])


def test_same_pick_in_both_sleeves_adds_up_and_respects_cap():
    prices = np.array([[10.0, 10.0], [11.0, 10.0], [12.0, 10.0], [13.0, 10.0]])

    uncapped = make_alpha(["A", "B"], top_n=1)
    capped = make_alpha(["A", "B"], top_n=1, max_weight=0.6)

    assert uncapped.target_weights(prices)[0] == pytest.approx(1.0)
    assert capped.target_weights(prices) == pytest.approx([0.6, 0.0])


def test_min_price_excludes_cheap_stocks():
    prices = np.array([[1.0, 10.0], [2.0, 10.5], [3.0, 11.0], [4.0, 11.5]])

    weights = make_alpha(["A", "B"], top_n=1, min_price=5.0).target_weights(prices)

    assert weights == pytest.approx([0.0, 1.0])


@pytest.mark.parametrize(
    ("params", "message"),
    [
        ({"sleeves": {"value": 1.0}}, "unknown sleeves"),
        ({"sleeves": {"momentum": 0.8, "high_52_week": 0.4}}, "at most 1"),
        ({"top_n": 0}, "top_n"),
        ({"rebalance": "weekly"}, "rebalance"),
        ({"max_weight": 0.0}, "max_weight"),
        ({"skip": 5}, "skip"),
    ],
)
def test_invalid_parameters_are_rejected(params, message):
    with pytest.raises(ValueError, match=message):
        make_alpha(["A", "B"], **params)


def daily_closes(days: int, growth: dict[str, float]) -> dict[str, list[float]]:
    return {
        ticker: [100.0 * (1 + rate) ** i for i in range(days)] for ticker, rate in growth.items()
    }


def test_end_to_end_rebalances_monthly_and_never_holds_benchmark():
    # 2024-01-02 through 2024-05-05; A trends up fastest, SPY is only the benchmark.
    closes = daily_closes(125, {"A": 0.004, "B": 0.001, "C": -0.001, "SPY": 0.002})
    alpha = AllocationAlpha(
        "US", "day", ["A", "B", "C"], "2024-02-15", "2024-05-01",
        sleeves={"momentum": 1.0}, top_n=1, lookback=20, skip=5, min_price=0.0,
        benchmark="SPY",
    )

    result = run_backtest(StaticProvider(closes), alpha, "day", "2024-01-02", "2024-05-01")

    rebalance_days = [timestamp.date() for timestamp, _ in alpha.holdings]
    assert rebalance_days == [
        dt.date(2024, 2, 15),
        dt.date(2024, 3, 1),
        dt.date(2024, 4, 1),
        dt.date(2024, 5, 1),
    ]
    assert all(holdings == {"A": 1.0} for _, holdings in alpha.holdings)
    assert alpha.get_tickers() == ["A", "B", "C", "SPY"]
    assert result["SPY"].max() == 0.0
    # Trades on the 15th are filled from the next bar.
    assert result["timestamp"][0].date() == dt.date(2024, 2, 16)


def test_quarterly_schedule():
    closes = daily_closes(200, {"A": 0.002, "B": 0.001})
    alpha = AllocationAlpha(
        "US", "day", ["A", "B"], "2024-01-02", "2024-07-19",
        top_n=1, lookback=10, skip=0, high_window=10, rebalance="quarterly", min_price=0.0,
    )

    run_backtest(StaticProvider(closes), alpha, "day", "2024-01-02", "2024-07-19")

    assert [timestamp.date() for timestamp, _ in alpha.holdings] == [
        dt.date(2024, 1, 2),
        dt.date(2024, 4, 1),
        dt.date(2024, 7, 1),
    ]


def test_signals_do_not_see_future_prices():
    closes = daily_closes(70, {"A": 0.003, "B": 0.001})
    shocked = {ticker: list(values) for ticker, values in closes.items()}
    # After the 2024-02-01 rebalance, B jumps; the February decision must not change.
    feb_first = (dt.date(2024, 2, 1) - dt.date(2024, 1, 2)).days
    shocked["B"][feb_first + 1:] = [value * 3 for value in shocked["B"][feb_first + 1:]]

    def february_holdings(data):
        alpha = AllocationAlpha(
            "US", "day", ["A", "B"], "2024-01-20", "2024-03-11",
            sleeves={"momentum": 1.0}, top_n=1, lookback=29, skip=0, min_price=0.0,
        )
        run_backtest(StaticProvider(data), alpha, "day", "2024-01-02", "2024-03-11")
        return dict((t.date(), h) for t, h in alpha.holdings)

    assert february_holdings(closes)[dt.date(2024, 2, 1)] == {"A": 1.0}
    assert february_holdings(shocked)[dt.date(2024, 2, 1)] == {"A": 1.0}
    assert february_holdings(shocked)[dt.date(2024, 3, 1)] == {"B": 1.0}


def test_warmup_period_covers_lookback():
    alpha = make_alpha(["A"], lookback=252, high_window=252)

    assert alpha.warmup_period() >= dt.timedelta(days=365)


def test_market_slice_with_missing_price_is_ineligible():
    alpha = make_alpha(["A", "B"], top_n=2, sleeves={"momentum": 1.0}, lookback=2)
    for i, (a, b) in enumerate([(10.0, 10.0), (11.0, None), (12.0, 10.0), (13.0, 10.5)]):
        alpha.update(
            pl.DataFrame(
                {"timestamp": [dt.datetime(2024, 1, 2 + i)], "A_close": [a], "B_close": [b]},
                schema={
                    "timestamp": pl.Datetime("us"),
                    "A_close": pl.Float64,
                    "B_close": pl.Float64,
                },
            )
        )

    # With lookback 2, B's start price is the gap, so only A is ranked.
    assert alpha.target_weights(np.vstack(alpha._history)) == pytest.approx([1.0, 0.0])
