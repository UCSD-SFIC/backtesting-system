from __future__ import annotations

import polars as pl
from typing import Optional

from data.providers import DataProvider
from engine.history import combine_ticker_histories
from engine.weights import build_weight_frame
from engine.utils import timeit
from strategy.alpha import Alpha


class BacktestEngine:
    def __init__(self, data_provider: Optional[DataProvider]):
        self._data_provider = data_provider

    def add_exponential_moving_average(
        self,
        history: pl.DataFrame,
        ticker: str,
        window: int,
    ) -> pl.DataFrame:
        """Add a close-price exponential moving average column for one ticker."""
        if window <= 0:
            raise ValueError("window must be greater than 0")

        close_column = f"{ticker}_close"
        if close_column not in history.columns:
            raise ValueError(f"{close_column} is missing from history")

        return history.sort("timestamp").with_columns(
            pl.col(close_column)
            .ewm_mean(span=window, adjust=False)
            .alias(f"{ticker}_ema_{window}")
        )

    def add_indicators(self, history: pl.DataFrame, alpha: Alpha) -> pl.DataFrame:
        """Materialize any engine-supported indicators requested by a strategy."""
        indicator_specs = getattr(alpha, "get_required_indicators", lambda: [])()
        enriched_history = history

        for indicator_spec in indicator_specs:
            indicator_type = indicator_spec.get("type")
            if indicator_type == "exponential_moving_average":
                enriched_history = self.add_exponential_moving_average(
                    enriched_history,
                    indicator_spec["ticker"],
                    indicator_spec["window"],
                )
            else:
                raise ValueError(f"Unsupported indicator type: {indicator_type}")

        return enriched_history

    def fetch_history(
        self,
        tickers: list[str],
        timespan: str,
        from_time: str,
        to_time: str,
    ) -> dict[str, pl.DataFrame]:
        if self._data_provider is None:
            raise ValueError("Data provider is required to fetch history")
        return self._data_provider.get_history(tickers, timespan, from_time, to_time)

    @timeit
    def run_portfolio_backtest(
        self,
        history: pl.DataFrame,
        weights: pl.DataFrame,
        tickers: list[str],
    ) -> pl.DataFrame:
        combined_history = history.lazy()
        weights_lazy = (
            weights.lazy()
            .sort("timestamp")
            .select(
                pl.col("timestamp").alias("rebalance_date"),
                *[pl.col(ticker) for ticker in tickers],
            )
        )

        result = combined_history.join_asof(
            weights_lazy,
            left_on="timestamp",
            right_on="rebalance_date",
            strategy="backward",
        ).drop_nulls()

        for ticker in tickers:
            result = result.with_columns(
                pl.col(f"{ticker}_return")
                .cum_prod()
                .over("rebalance_date")
                .alias(f"{ticker}_period_return")
            )

        allocated_weight = pl.sum_horizontal([pl.col(ticker) for ticker in tickers])
        result = result.with_columns(
            allocated_weight.alias("allocated_weight"),
            pl.lit(1.0).sub(allocated_weight).alias("cash_weight"),
        )

        result = result.with_columns(
            pl.sum_horizontal(
                [pl.col(f"{ticker}_period_return").mul(pl.col(ticker)) for ticker in tickers]
            )
            .add(pl.col("cash_weight"))
            .alias("period_total_weighted")
        )

        aggregated_period = (
            result.group_by("rebalance_date")
            .agg(pl.col("period_total_weighted").last())
            .sort("rebalance_date")
            .with_columns(
                pl.col("period_total_weighted")
                .shift()
                .fill_null(1)
                .cum_prod()
                .alias("previous_period_last")
            )
        )

        result = result.join(aggregated_period, on="rebalance_date", how="right")

        result = (
            result.with_columns(
                [
                    pl.col(f"{ticker}_return")
                    .cum_prod()
                    .sub(1)
                    .alias(f"{ticker}_cumulative_return")
                    for ticker in tickers
                ]
            )
            .with_columns(
                pl.col("period_total_weighted")
                .mul(pl.col("previous_period_last"))
                .alias("overall_growth")
            )
            .with_columns(pl.col("overall_growth").sub(1).alias("overall_cumulative_return"))
            .sort("timestamp")
        )

        return result.collect()

    def run(
        self,
        alpha: Alpha,
        timespan: str,
        from_time: str,
        to_time: str,
    ) -> pl.DataFrame:
        tickers = alpha.get_tickers()
        history_raw = self.fetch_history(tickers, timespan, from_time, to_time)
        combined_history = combine_ticker_histories(history_raw)
        combined_history = self.add_indicators(combined_history, alpha)
        weights = build_weight_frame(alpha, combined_history)
        return self.run_portfolio_backtest(combined_history, weights, tickers)
