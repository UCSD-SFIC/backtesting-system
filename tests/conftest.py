from __future__ import annotations

import polars as pl
import pytest


# Shared deterministic fixtures for core backtest tests.


@pytest.fixture
def price_history() -> dict[str, pl.DataFrame]:
    # Four aligned dates with opposite price paths for two tickers.
    days = pl.Series(
        [
            1704171600000,
            1704258000000,
            1704344400000,
            1704430800000,
        ]
    )

    return {
        "A": pl.DataFrame({"timestamp": days, "close": [1.0, 2.0, 4.0, 8.0]}),
        "B": pl.DataFrame({"timestamp": days, "close": [1.0, 0.5, 0.25, 0.125]}),
    }


@pytest.fixture
def rebalance_weights() -> pl.DataFrame:
    # Two rebalance rows used to verify period-based weighting.
    return pl.DataFrame(
        {
            "A": [0.5, 0.2],
            "B": [0.5, 0.8],
            "timestamp": pl.Series(
                ["01/01/2024 5:00:00", "04/01/2024 5:00:00"]
            ).str.strptime(pl.Datetime, "%d/%m/%Y %H:%M:%S"),
        }
    )
