from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

from engine_layer.history import combine_ticker_histories


# Tests for the raw per-ticker history to combined-history contract.


def test_combine_ticker_histories_builds_expected_schema(price_history):
    # Verifies output columns, datetime conversion, and per-ticker returns.
    result = combine_ticker_histories(price_history)

    assert result.columns == [
        "timestamp",
        "A_close",
        "A_return",
        "B_close",
        "B_return",
    ]
    assert result.schema["timestamp"] == pl.Datetime("us")
    assert result["A_return"].to_list() == pytest.approx([1.0, 2.0, 2.0, 2.0])
    assert result["B_return"].to_list() == pytest.approx([1.0, 0.5, 0.5, 0.5])


def test_combine_ticker_histories_coalesces_staggered_timestamps():
    # Verifies full joins keep dates from every ticker without null timestamps.
    history = {
        "A": pl.DataFrame(
            {
                "timestamp": [1704171600000, 1704258000000],
                "close": [10.0, 12.0],
            }
        ),
        "B": pl.DataFrame(
            {
                "timestamp": [1704258000000, 1704344400000],
                "close": [20.0, 18.0],
            }
        ),
    }

    result = combine_ticker_histories(history)

    assert result.height == 3
    assert "timestamp_right" not in result.columns
    assert result["timestamp"].null_count() == 0
    assert result["timestamp"].to_list() == [
        dt.datetime(2024, 1, 2, 5, 0),
        dt.datetime(2024, 1, 3, 5, 0),
        dt.datetime(2024, 1, 4, 5, 0),
    ]
    assert result["A_close"].to_list() == pytest.approx([10.0, 12.0, None])
    assert result["B_close"].to_list() == pytest.approx([None, 20.0, 18.0])


def test_combine_ticker_histories_rejects_empty_history():
    # Verifies callers get a clear error for missing market data.
    with pytest.raises(ValueError, match="history cannot be empty"):
        combine_ticker_histories({})
