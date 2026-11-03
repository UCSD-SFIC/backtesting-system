from __future__ import annotations

import datetime as dt
from collections import deque

import numpy as np
import polars as pl

from strategy.alpha import Alpha
from strategy.signals import SIGNALS, cap_weights, top_n

REBALANCE_MONTHS = {
    "monthly": set(range(1, 13)),
    "quarterly": {1, 4, 7, 10},
}


class AllocationAlpha(Alpha):
    """
    Ranks a stock universe on a schedule and holds the top names per sleeve.

    Each sleeve gets a fixed share of capital, ranks the eligible universe on
    one signal, and spreads its share equally over its top `top_n` names. A
    stock picked by several sleeves gets the sum of their weights. With
    `max_weight`, any position over the cap is trimmed and the excess spread
    over the other holdings; anything that cannot be placed stays in cash.

    Signals use closes up to and including the rebalance bar; the engine
    applies the weights from the next bar, so there is no look-ahead.
    The portfolio first trades on the first bar on or after `start` and then
    on the first bar of each month (or quarter). Bars before `start` are only
    used to warm up the signals.
    """

    def __init__(
        self,
        universe: str,
        resolution: str,
        ticker: list[str],
        start: str,
        end: str,
        sleeves: dict[str, float] | None = None,
        top_n: int = 20,
        max_weight: float | None = None,
        rebalance: str = "monthly",
        lookback: int = 252,
        skip: int = 21,
        high_window: int = 252,
        min_price: float = 5.0,
        benchmark: str | None = None,
    ):
        sleeves = sleeves or {"momentum": 0.7, "high_52_week": 0.3}
        unknown = set(sleeves) - set(SIGNALS)
        if unknown:
            raise ValueError(f"unknown sleeves {sorted(unknown)}; choose from {sorted(SIGNALS)}")
        if any(share < 0 for share in sleeves.values()):
            raise ValueError("sleeve shares cannot be negative")
        if not 0 < sum(sleeves.values()) <= 1 + 1e-9:
            raise ValueError("sleeve shares must add up to more than 0 and at most 1")
        if top_n < 1:
            raise ValueError("top_n must be at least 1")
        if rebalance not in REBALANCE_MONTHS:
            raise ValueError(f"rebalance must be one of {sorted(REBALANCE_MONTHS)}")
        if max_weight is not None and not 0 < max_weight <= 1:
            raise ValueError("max_weight must be in (0, 1]")
        if not 0 <= skip < lookback:
            raise ValueError("skip must be at least 0 and less than lookback")

        self.universe = universe
        self.resolution = resolution
        self.start = dt.date.fromisoformat(start)
        self.end = end
        self.investable = list(ticker)
        self.benchmark = benchmark
        self.sleeves = sleeves
        self.top_n = top_n
        self.max_weight = max_weight
        self.rebalance = rebalance
        self.lookback = lookback
        self.skip = skip
        self.high_window = high_window
        self.min_price = min_price

        self._tickers = self.investable + (
            [benchmark] if benchmark and benchmark not in self.investable else []
        )
        self._close_columns = [f"{ticker}_close" for ticker in self.investable]
        self._history: deque[np.ndarray] = deque(maxlen=max(lookback, high_window) + 1)
        self._weights = [0.0] * len(self._tickers)
        self._rebalanced = False
        self._last_month: tuple[int, int] | None = None
        self._started = False
        self.holdings: list[tuple[dt.datetime, dict[str, float]]] = []

    def get_tickers(self) -> list[str]:
        return self._tickers

    def get_weights(self) -> list[float]:
        return self._weights

    def should_rebalance(self) -> bool:
        return self._rebalanced

    def warmup_period(self) -> dt.timedelta:
        # Trading bars to calendar days, with a margin for holidays.
        bars = max(self.lookback, self.high_window)
        return dt.timedelta(days=int(bars * 7 / 5) + 30)

    def _is_rebalance_bar(self, timestamp: dt.datetime) -> bool:
        month = (timestamp.year, timestamp.month)
        new_month = self._last_month is not None and month != self._last_month
        self._last_month = month
        if timestamp.date() < self.start:
            return False
        if not self._started:
            self._started = True
            return True
        return new_month and timestamp.month in REBALANCE_MONTHS[self.rebalance]

    def target_weights(self, prices: np.ndarray) -> np.ndarray:
        """Target weights over the investable universe from a price matrix."""
        latest = prices[-1]
        weights = np.zeros(prices.shape[1])
        for name, share in self.sleeves.items():
            if name == "momentum":
                scores = SIGNALS[name](prices, self.lookback, self.skip)
            else:
                scores = SIGNALS[name](prices, self.high_window)
            scores = np.where(latest >= self.min_price, scores, np.nan)
            picks = top_n(scores, self.top_n)
            if len(picks):
                weights[picks] += share / len(picks)
        if self.max_weight is not None:
            weights = cap_weights(weights, self.max_weight)
        return weights

    def update(self, market_slice: pl.DataFrame) -> None:
        timestamp = market_slice["timestamp"][0]
        row = market_slice.select(self._close_columns).row(0)
        self._history.append(np.array([np.nan if v is None else v for v in row], dtype=float))

        self._rebalanced = self._is_rebalance_bar(timestamp)
        if not self._rebalanced:
            return

        target = self.target_weights(np.vstack(self._history))
        self._weights = [float(w) for w in target] + [0.0] * (
            len(self._tickers) - len(self.investable)
        )
        self.holdings.append(
            (
                timestamp,
                {
                    ticker: float(weight)
                    for ticker, weight in zip(self.investable, target, strict=True)
                    if weight > 0
                },
            )
        )
