from __future__ import annotations

import polars as pl

from engine.utils import validate_weights, timeit
from strategy.alpha import Alpha


@timeit
def build_weight_frame(alpha: Alpha, combined_history: pl.DataFrame) -> pl.DataFrame:
    """Build per-timestamp weight table by advancing strategy state through time."""
    weights = combined_history.select(pl.col("timestamp"))
    tickers = alpha.get_tickers()

    weight_updates: list[list[float]] = []
    for ts in weights["timestamp"]:
        current_slice = combined_history.filter(pl.col("timestamp") == ts)
        alpha.update(current_slice)
        weight_updates.append(alpha.get_weights())

    for i, ticker in enumerate(tickers):
        weights = weights.with_columns(
            pl.Series([w[i] for w in weight_updates]).shift().alias(ticker)
        )

    weights = weights.drop_nulls()
    validate_weights(weights, tickers)
    return weights
