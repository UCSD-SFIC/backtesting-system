"""A portfolio that holds user-supplied target weights on a simple schedule."""

from __future__ import annotations

import datetime as dt
import math

import polars as pl

from strategy.alpha import Alpha


class FixedWeightAlpha(Alpha):
    """Apply a fixed target portfolio on the first bar and each scheduled period."""

    def __init__(
        self,
        universe: str,
        resolution: str,
        ticker: list[str],
        start: str,
        end: str,
        weights: dict[str, float],
        rebalance: str = "monthly",
        benchmark: str | None = None,
    ) -> None:
        if rebalance not in {"monthly", "quarterly"}:
            raise ValueError("rebalance must be monthly or quarterly")
        if set(weights) != set(ticker) or not weights or any(
            not isinstance(weight, (int, float)) or not math.isfinite(weight) or weight < 0
            for weight in weights.values()
        ) or not 0 < sum(weights.values()) <= 1 + 1e-9:
            raise ValueError(
                "weights must cover each ticker, be finite and nonnegative, and sum to (0, 1]"
            )
        self.universe = universe
        self.resolution = resolution
        self.start = dt.date.fromisoformat(start)
        self.end = dt.date.fromisoformat(end)
        self.investable = list(ticker)
        self.benchmark = benchmark
        self.target = {symbol: float(weights[symbol]) for symbol in ticker}
        self.rebalance = rebalance
        self._tickers = self.investable + (
            [benchmark] if benchmark and benchmark not in self.investable else []
        )
        self._weights = [0.0] * len(self._tickers)
        self._last_month: tuple[int, int] | None = None
        self._started = False
        self._rebalanced = False
        self.holdings: list[tuple[dt.datetime, dict[str, float]]] = []

    def get_tickers(self) -> list[str]:
        return list(self._tickers)

    def get_weights(self) -> list[float]:
        return list(self._weights)

    def should_rebalance(self) -> bool:
        return self._rebalanced

    def update(self, market_slice: pl.DataFrame) -> None:
        timestamp = market_slice["timestamp"][0]
        month = (timestamp.year, timestamp.month)
        new_month = self._last_month is not None and month != self._last_month
        self._last_month = month
        self._rebalanced = False
        if timestamp.date() < self.start or timestamp.date() > self.end:
            return
        if not self._started:
            self._started = True
            self._rebalanced = True
        elif new_month and (
            self.rebalance == "monthly" or timestamp.month in {1, 4, 7, 10}
        ):
            self._rebalanced = True
        if self._rebalanced:
            self._weights = [self.target[symbol] for symbol in self.investable] + [0.0] * (
                len(self._tickers) - len(self.investable)
            )
            self.holdings.append((timestamp, {
                symbol: weight for symbol, weight in self.target.items() if weight > 0
            }))
