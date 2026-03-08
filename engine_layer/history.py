from __future__ import annotations

import polars as pl


def combine_ticker_histories(history: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Combine per-ticker history into one aligned table of closes and returns."""
    tickers = list(history.keys())
    if not tickers:
        raise ValueError("history cannot be empty")

    first_ticker = tickers[0]
    base_df = (
        history[first_ticker]
        .lazy()
        .select(
            [
                pl.from_epoch(pl.col("timestamp"), time_unit="ms")
                .cast(pl.Datetime("us"))
                .alias("timestamp"),
                pl.col("close").alias(f"{first_ticker}_close"),
                pl.col("close")
                .pct_change()
                .add(1)
                .fill_null(1)
                .alias(f"{first_ticker}_return"),
            ]
        )
    )

    for ticker in tickers[1:]:
        base_df = base_df.join(
            history[ticker]
            .lazy()
            .select(
                [
                    pl.from_epoch(pl.col("timestamp"), time_unit="ms")
                    .cast(pl.Datetime("us"))
                    .alias("timestamp"),
                    pl.col("close").alias(f"{ticker}_close"),
                    pl.col("close")
                    .pct_change()
                    .add(1)
                    .fill_null(1)
                    .alias(f"{ticker}_return"),
                ]
            ),
            on="timestamp",
            how="full",
        )

    return base_df.collect().sort("timestamp")
