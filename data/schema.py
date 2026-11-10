from __future__ import annotations

import polars as pl


# Every provider returns one frame per ticker with exactly these columns.
# `timestamp` is the bar open time as UTC epoch milliseconds.
OHLCV_SCHEMA: dict[str, pl.DataType] = {
    "timestamp": pl.Int64(),
    "open": pl.Float64(),
    "high": pl.Float64(),
    "low": pl.Float64(),
    "close": pl.Float64(),
    "volume": pl.Float64(),
}

OHLCV_COLUMNS = list(OHLCV_SCHEMA)
PRICE_COLUMNS = ["open", "high", "low", "close"]


def normalize_ohlcv(df: pl.DataFrame) -> pl.DataFrame:
    """Select, cast, and sort provider output into the shared OHLCV schema."""
    missing = [column for column in OHLCV_COLUMNS if column not in df.columns]
    if missing:
        raise ValueError(f"history is missing required columns: {missing}")

    return df.select(
        [pl.col(column).cast(dtype) for column, dtype in OHLCV_SCHEMA.items()]
    ).sort("timestamp")
