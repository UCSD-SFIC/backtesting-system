from __future__ import annotations

from data.providers import _flatten_yfinance_columns, _polygon_timespan, _yfinance_interval


def test_polygon_timespan_supports_two_hour_candles():
    assert _polygon_timespan("2hour") == (2, "hour")


def test_yfinance_uses_one_hour_source_for_two_hour_candles():
    assert _yfinance_interval("2hour") == "1h"


def test_yfinance_column_flattener_handles_single_ticker_multiindex_shape():
    columns = [("Datetime", ""), ("Close", "SPY")]

    assert _flatten_yfinance_columns(columns) == ["Datetime", "Close"]
