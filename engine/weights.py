from __future__ import annotations

import polars as pl

from engine.utils import timeit, validate_weights
from strategy.alpha import Alpha


@timeit
def build_weight_frame(alpha: Alpha, combined_history: pl.DataFrame) -> pl.DataFrame:
    """Build per-timestamp weight table by advancing strategy state through time."""
    weights = combined_history.select(pl.col("timestamp"))
    tickers = alpha.get_tickers()

    # Timestamps are unique after combine_ticker_histories, so each bar is one
    # row; slicing by position avoids rescanning the whole table every step.
    weight_updates: list[list[float]] = []
    for row in range(combined_history.height):
        alpha.update(combined_history.slice(row, 1))
        weight_updates.append(alpha.get_weights())

    for i, ticker in enumerate(tickers):
        weights = weights.with_columns(
            pl.Series([w[i] for w in weight_updates]).shift().alias(ticker)
        )

    weights = weights.drop_nulls()
    validate_weights(weights, tickers)
    return weights
