from __future__ import annotations

import polars as pl
import pytest

from data.providers import DataProvider
from pipeline.backtest import run_backtest, summarize_backtest
from strategy.alpha import Alpha
from strategy.sample_alpha import SampleAlpha

# End-to-end runs through provider -> history -> weights -> backtest -> metrics
# with hand-checkable data, so engine refactors cannot silently change results.


class StaticProvider(DataProvider):
    name = "static"

    def __init__(self, closes: dict[str, list[float]], day_ms: int = 86_400_000):
        self._closes = closes
        self._day_ms = day_ms

    def get_history(self, tickers, timespan, from_time, to_time):
        start_ms = 1704171600000
        return {
            ticker: pl.DataFrame(
                {
                    "timestamp": [
                        start_ms + i * self._day_ms for i in range(len(self._closes[ticker]))
                    ],
                    "open": self._closes[ticker],
                    "high": self._closes[ticker],
                    "low": self._closes[ticker],
                    "close": self._closes[ticker],
                    "volume": [1.0] * len(self._closes[ticker]),
                }
            )
            for ticker in tickers
        }


class FixedWeightAlpha(Alpha):
    def __init__(self, tickers: list[str], weights: list[float]):
        self._tickers = tickers
        self._weights = weights
        self.seen_closes: list[float] = []

    def get_tickers(self) -> list[str]:
        return self._tickers

    def get_weights(self) -> list[float]:
        return self._weights

    def update(self, market_slice: pl.DataFrame) -> None:
        assert market_slice.height == 1
        self.seen_closes.append(market_slice[f"{self._tickers[0]}_close"][0])


def test_fully_invested_run_matches_hand_computed_return():
    provider = StaticProvider({"A": [1.0, 2.0, 4.0, 8.0], "B": [1.0, 1.0, 1.0, 1.0]})
    alpha = FixedWeightAlpha(["A", "B"], [1.0, 0.0])

    result = run_backtest(provider, alpha, "day", "2024-01-02", "2024-01-05")

    # The first bar only produces a signal; A doubles on each of the next three.
    assert result["overall_cumulative_return"][-1] == pytest.approx(7.0)
    assert alpha.seen_closes == [1.0, 2.0, 4.0, 8.0]


def test_half_cash_run_compounds_each_bar():
    provider = StaticProvider({"A": [1.0, 2.0, 4.0], "B": [1.0, 1.0, 1.0]})
    alpha = FixedWeightAlpha(["A", "B"], [0.5, 0.0])

    result = run_backtest(provider, alpha, "day", "2024-01-02", "2024-01-04")

    # Rebalanced to 50% A / 50% cash every bar: 1.5 * 1.5 growth.
    assert result["overall_cumulative_return"][-1] == pytest.approx(1.25)


def test_sample_alpha_end_to_end_switches_on_moving_average_cross():
    rising = [float(10 + i) for i in range(25)]
    falling = [float(34 - i) for i in range(25)]
    provider = StaticProvider({"SPY": rising + falling, "SH": falling[::-1] + rising[::-1]})
    alpha = SampleAlpha("US", "day", ["SPY", "SH"], "2024-01-02", "2024-03-01")

    result = run_backtest(provider, alpha, "day", "2024-01-02", "2024-03-01")
    metrics = summarize_backtest(result, benchmark_ticker="SPY")

    assert result.height == 49
    assert metrics["total_return"] == pytest.approx(
        float(result["overall_cumulative_return"][-1])
    )
    assert metrics["max_drawdown"] < 0
