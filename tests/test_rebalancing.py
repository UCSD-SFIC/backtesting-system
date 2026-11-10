from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

from data.providers import DataProvider
from engine.backtest_engine import BacktestEngine
from pipeline.backtest import run_backtest
from strategy.alpha import Alpha


def test_missing_bar_for_held_asset_is_not_silently_flat():
    history = pl.DataFrame({
        "timestamp": [dt.datetime(2024, 1, 1), dt.datetime(2024, 1, 2)],
        "A_return": [1.0, None], "A_close": [10.0, None],
    })
    weights = pl.DataFrame({"timestamp": [dt.datetime(2024, 1, 1)], "A": [1.0]})
    with pytest.raises(ValueError, match="missing return.*A"):
        BacktestEngine(None).run_portfolio_backtest(history, weights, ["A"])

# Tests for scheduled rebalancing, turnover, trading costs, and tickers whose
# history does not cover the whole backtest. Expected values are hand-computed.

DAY_MS = 86_400_000
START_MS = 1704171600000


class StaticProvider(DataProvider):
    name = "static"

    def __init__(self, closes: dict[str, list[float]], offsets: dict[str, int] | None = None):
        self._closes = closes
        self._offsets = offsets or {}

    def get_history(self, tickers, timespan, from_time, to_time):
        histories = {}
        for ticker in tickers:
            closes = self._closes[ticker]
            offset = self._offsets.get(ticker, 0)
            histories[ticker] = pl.DataFrame(
                {
                    "timestamp": [START_MS + (offset + i) * DAY_MS for i in range(len(closes))],
                    "open": closes,
                    "high": closes,
                    "low": closes,
                    "close": closes,
                    "volume": [1.0] * len(closes),
                }
            )
        return histories


class ScheduledAlpha(Alpha):
    """Targets fixed weights and rebalances only on the listed bar numbers."""

    def __init__(self, tickers: list[str], weights: list[float], rebalance_bars: set[int]):
        self._tickers = tickers
        self._weights = weights
        self._rebalance_bars = rebalance_bars
        self._bar = -1

    def get_tickers(self) -> list[str]:
        return self._tickers

    def get_weights(self) -> list[float]:
        return self._weights

    def update(self, market_slice: pl.DataFrame) -> None:
        self._bar += 1

    def should_rebalance(self) -> bool:
        return self._bar in self._rebalance_bars


def run(closes, weights, rebalance_bars, cost_bps=0.0, offsets=None) -> pl.DataFrame:
    provider = StaticProvider(closes, offsets)
    alpha = ScheduledAlpha(list(closes), weights, rebalance_bars)
    return run_backtest(provider, alpha, "day", "2024-01-02", "2024-02-01", cost_bps=cost_bps)


def test_positions_drift_between_scheduled_rebalances():
    result = run({"A": [1.0, 2.0, 4.0], "B": [1.0, 1.0, 1.0]}, [0.5, 0.5], {0})

    # Buy-and-hold from bar 0: half in A (x4), half in B (x1).
    assert result["overall_growth"][-1] == pytest.approx(2.5)
    assert result["rebalance_date"].n_unique() == 1


def test_turnover_compares_target_with_drifted_weights():
    result = run({"A": [1.0, 2.0, 4.0, 4.0], "B": [1.0] * 4}, [0.5, 0.5], {0, 2})

    turnover = result.group_by("rebalance_date").agg(pl.col("rebalance_turnover").first())
    # Entry trade from cash is 1.0; then A drifted to 0.8 and B to 0.2, so
    # rebalancing back to 50/50 trades 0.3 + 0.3.
    assert sorted(turnover["rebalance_turnover"].to_list()) == pytest.approx([0.6, 1.0])


def test_costs_are_charged_on_each_rebalance():
    closes = {"A": [1.0, 2.0, 4.0, 4.0], "B": [1.0] * 4}

    free = run(closes, [0.5, 0.5], {0, 2})
    costly = run(closes, [0.5, 0.5], {0, 2}, cost_bps=100)

    assert free["overall_growth"][-1] == pytest.approx(2.5)
    assert costly["overall_growth"][-1] == pytest.approx(2.5 * (1 - 0.01) * (1 - 0.006))


def test_negative_cost_is_rejected():
    with pytest.raises(ValueError, match="cost_bps"):
        BacktestEngine(None, cost_bps=-1)


def test_ticker_listed_late_does_not_drop_earlier_bars():
    # C only has data from bar 2 onward; A must still be tracked from bar 1.
    closes = {"A": [1.0, 2.0, 4.0, 8.0], "C": [10.0, 11.0]}

    result = run(closes, [1.0, 0.0], {0}, offsets={"C": 2})

    assert result.height == 3
    assert result["overall_growth"].to_list() == pytest.approx([2.0, 4.0, 8.0])
