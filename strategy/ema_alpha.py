from __future__ import annotations

import polars as pl

from strategy.alpha import Alpha


class ExponentialMovingAverageAlpha(Alpha):
    """Buy SPY dips only when the broader EMA regime is bullish."""

    def __init__(
        self,
        universe: str,
        resolution: str,
        ticker: list[str],
        start: str,
        end: str,
        ema_window: int = 50,
        regime_window: int = 200,
    ):
        if len(ticker) < 2:
            raise ValueError("ExponentialMovingAverageAlpha requires at least two tickers")
        if ema_window <= 0:
            raise ValueError("ema_window must be greater than 0")
        if regime_window <= 0:
            raise ValueError("regime_window must be greater than 0")
        if ema_window >= regime_window:
            raise ValueError("ema_window must be less than regime_window")

        self.universe = universe
        self.resolution = resolution
        self.ticker = ticker
        self.current_time = start
        self.start = start
        self.end = end
        self.ema_window = ema_window
        self.regime_window = regime_window
        self.weight = [0.0] * len(ticker)

    def get_required_indicators(self) -> list[dict[str, int | str]]:
        primary_ticker = self.ticker[0]
        return [
            {
                "type": "exponential_moving_average",
                "ticker": primary_ticker,
                "window": self.ema_window,
            },
            {
                "type": "exponential_moving_average",
                "ticker": primary_ticker,
                "window": self.regime_window,
            },
        ]

    def get_tickers(self) -> list[str]:
        return self.ticker

    def get_weights(self) -> list[float]:
        return self.weight

    def update(self, market_slice: pl.DataFrame) -> None:
        self.current_time = market_slice["timestamp"][0]
        primary_ticker = self.ticker[0]
        close_price = market_slice[f"{primary_ticker}_close"][0]
        ema_value = market_slice[f"{primary_ticker}_ema_{self.ema_window}"][0]
        regime_ema = market_slice[f"{primary_ticker}_ema_{self.regime_window}"][0]

        is_dip = close_price < ema_value
        is_bullish_regime = close_price > regime_ema
        if is_dip and is_bullish_regime:
            self.weight = [1.0, 0.0] + [0.0] * (len(self.ticker) - 2)
        else:
            self.weight = [0.0] * len(self.ticker)


emaAlpha = ExponentialMovingAverageAlpha
