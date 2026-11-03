from __future__ import annotations

import polars as pl

from engine.utils import timeit, validate_weights
from strategy.alpha import Alpha


@timeit
def build_weight_frame(alpha: Alpha, combined_history: pl.DataFrame) -> pl.DataFrame:
    """
    Build the rebalance table by advancing strategy state through time.

    Weights decided on a bar's close take effect from the next bar, so each
    row is shifted by one. Only bars where the strategy rebalanced are kept.
    """
    tickers = alpha.get_tickers()

    # Timestamps are unique after combine_ticker_histories, so each bar is one
    # row; slicing by position avoids rescanning the whole table every step.
    weight_updates: list[list[float]] = []
    rebalances: list[bool] = []
    for row in range(combined_history.height):
        alpha.update(combined_history.slice(row, 1))
        weight_updates.append([float(weight) for weight in alpha.get_weights()])
        rebalances.append(alpha.should_rebalance())

    decided = pl.DataFrame(weight_updates, schema=tickers, orient="row").with_columns(
        pl.Series("rebalance", rebalances)
    )
    weights = (
        pl.concat([combined_history.select("timestamp"), decided.shift()], how="horizontal")
        .drop_nulls()
        .filter(pl.col("rebalance"))
        .drop("rebalance")
    )
    if weights.height == 0:
        raise ValueError(
            "The strategy never rebalanced. Check that the date range covers its "
            "start date and has enough bars for its signals."
        )
    validate_weights(weights, tickers)
    return weights
