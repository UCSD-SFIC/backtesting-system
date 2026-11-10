from __future__ import annotations

import polars as pl


def _select_ticker_history(ticker: str, history: pl.DataFrame) -> pl.DataFrame:
    # Returns are computed on each ticker's own bars before alignment, so a
    # ticker that is missing on a date gets a null return there, not a gap fill.
    return history.select(
        [
            pl.from_epoch(pl.col("timestamp"), time_unit="ms")
            .cast(pl.Datetime("us"))
            .alias("timestamp"),
            pl.lit(ticker).alias("ticker"),
            pl.col("close").cast(pl.Float64).alias("close"),
            pl.col("close")
            .cast(pl.Float64)
            .pct_change()
            .add(1)
            .fill_null(1)
            .alias("return"),
        ]
    )


def combine_ticker_histories(history: dict[str, pl.DataFrame]) -> pl.DataFrame:
    """Combine per-ticker history into one aligned table of closes and returns."""
    tickers = list(history.keys())
    if not tickers:
        raise ValueError("history cannot be empty")

    # One concat + pivot instead of a chain of full joins: the join chain grows
    # quadratically with the number of tickers.
    long = pl.concat([_select_ticker_history(ticker, history[ticker]) for ticker in tickers])
    closes = long.pivot(on="ticker", index="timestamp", values="close")
    returns = long.pivot(on="ticker", index="timestamp", values="return")

    return (
        closes.select(
            "timestamp",
            *[pl.col(ticker).alias(f"{ticker}_close") for ticker in tickers],
        )
        .join(
            returns.select(
                "timestamp",
                *[pl.col(ticker).alias(f"{ticker}_return") for ticker in tickers],
            ),
            on="timestamp",
        )
        .select(
            "timestamp",
            *[
                column
                for ticker in tickers
                for column in (f"{ticker}_close", f"{ticker}_return")
            ],
        )
        .sort("timestamp")
    )
