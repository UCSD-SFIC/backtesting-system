from __future__ import annotations

import polars as pl

from alpha import Alpha


class sampleAlpha(Alpha):
    def __init__(
        self,
        universe,
        resolution,
        ticker,
        start,
        end,
        short_window=5,
        long_window=20,
    ):
        self.universe = universe
        self.resolution = resolution
        self.ticker = ticker
        self.current_time = start
        self.start = start
        self.end = end

        self.short_window = short_window
        self.long_window = long_window

        self.price_history = []
        self.short_ma = None
        self.long_ma = None
        self.position = 0
        self.weight = [1, 0]

    def get_weight(self):
        return self.weight

    def get_tickers(self):
        return self.ticker

    def _add_prices(self, price: pl.DataFrame):
        """Adds new price data and update moving averages"""
        primary_ticker = self.ticker[0]
        close_column = f"{primary_ticker}_close"
        close_price = price[close_column][0]
        self.price_history.append(close_price)

        # Calculate moving averages if we have enough data
        if len(self.price_history) >= self.short_window:
            self.short_ma = (
                sum(self.price_history[-self.short_window :]) / self.short_window
            )

        if len(self.price_history) >= self.long_window:
            self.long_ma = (
                sum(self.price_history[-self.long_window :]) / self.long_window
            )

    def update(self, market_slice: pl.DataFrame):
        """
        Update the strategy based on current price data
        """
        self.current_time = market_slice["timestamp"][0]
        self._add_prices(market_slice)

        if self.short_ma is None or self.long_ma is None:
            self.weight = [1, 0]
            return None

        self.weight = [1, 0] if self.short_ma > self.long_ma else [0, 1]
        return None

    def get_weights(self):
        return self.weight
