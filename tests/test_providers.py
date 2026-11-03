from __future__ import annotations

import sys
import types

import pandas as pd
import polars as pl
import pytest

from data.providers import (
    PolygonDataProvider,
    YFinanceDataProvider,
    _flatten_yfinance_columns,
    _polygon_timespan,
    _yfinance_interval,
)
from data.schema import OHLCV_COLUMNS


def test_polygon_timespan_supports_two_hour_candles():
    assert _polygon_timespan("2hour") == (2, "hour")


def test_yfinance_uses_one_hour_source_for_two_hour_candles():
    assert _yfinance_interval("2hour") == "1h"


def test_yfinance_column_flattener_handles_single_ticker_multiindex_shape():
    columns = [("Datetime", ""), ("Close", "SPY")]

    assert _flatten_yfinance_columns(columns) == ["Datetime", "Close"]


# Provider fetch tests use fake clients so they never touch the network.


def _yfinance_frame(index: pd.DatetimeIndex, ticker: str) -> pd.DataFrame:
    # Mirrors yf.download's single-ticker shape: (Price, Ticker) column MultiIndex.
    n = len(index)
    values = {
        "Adj Close": [9.0 + i for i in range(n)],
        "Close": [10.0 + i for i in range(n)],
        "High": [11.0 + i for i in range(n)],
        "Low": [9.0 + i for i in range(n)],
        "Open": [9.5 + i for i in range(n)],
        "Volume": [100] * n,
    }
    columns = pd.MultiIndex.from_tuples(
        [(name, ticker) for name in values], names=["Price", "Ticker"]
    )
    df = pd.DataFrame(list(zip(*values.values(), strict=True)), index=index, columns=columns)
    df.index.name = "Datetime" if index.tz is not None else "Date"
    return df


@pytest.fixture
def fake_yfinance(monkeypatch):
    calls: list[dict] = []
    frames: dict[str, pd.DataFrame] = {}

    def download(ticker, **kwargs):
        calls.append({"ticker": ticker, **kwargs})
        return frames.get(ticker, pd.DataFrame())

    module = types.SimpleNamespace(download=download)
    monkeypatch.setitem(sys.modules, "yfinance", module)
    return calls, frames


def test_yfinance_returns_normalized_ohlcv_and_includes_end_date(fake_yfinance):
    calls, frames = fake_yfinance
    frames["SPY"] = _yfinance_frame(pd.date_range("2024-01-02", periods=3, freq="D"), "SPY")

    result = YFinanceDataProvider().get_history(["SPY"], "day", "2024-01-01", "2024-01-04")

    assert calls[0]["start"] == "2024-01-01"
    assert calls[0]["end"] == "2024-01-05"
    assert calls[0]["interval"] == "1d"
    history = result["SPY"]
    assert history.columns == OHLCV_COLUMNS
    assert history.schema["timestamp"] == pl.Int64
    assert history["close"].to_list() == [10.0, 11.0, 12.0]
    assert history["timestamp"][0] == 1704153600000


def test_yfinance_two_hour_bars_aggregate_ohlcv(fake_yfinance):
    _, frames = fake_yfinance
    index = pd.date_range("2024-01-02 14:00", periods=4, freq="h", tz="UTC")
    frames["SPY"] = _yfinance_frame(index, "SPY")

    provider = YFinanceDataProvider()
    history = provider.get_history(["SPY"], "2hour", "2024-01-02", "2024-01-02")["SPY"]

    assert history.height == 2
    assert history["open"].to_list() == [9.5, 11.5]
    assert history["high"].to_list() == [12.0, 14.0]
    assert history["low"].to_list() == [9.0, 11.0]
    assert history["close"].to_list() == [11.0, 13.0]
    assert history["volume"].to_list() == [200.0, 200.0]


def test_yfinance_empty_download_raises(fake_yfinance):
    with pytest.raises(ValueError, match="No data returned for NOPE"):
        YFinanceDataProvider().get_history(["NOPE"], "day", "2024-01-01", "2024-01-04")


class _FakePolygonClient:
    def __init__(self, aggs):
        self.aggs = aggs
        self.calls: list[dict] = []

    def list_aggs(self, **kwargs):
        self.calls.append(kwargs)
        return iter(self.aggs)


def _polygon_provider(aggs) -> tuple[PolygonDataProvider, _FakePolygonClient]:
    provider = PolygonDataProvider.__new__(PolygonDataProvider)
    client = _FakePolygonClient(aggs)
    provider._client = client
    return provider, client


def test_polygon_paginates_and_normalizes():
    from polygon.rest.models import Agg

    aggs = [
        Agg(open=1, high=2, low=0.5, close=1.5, volume=10, vwap=1.2, timestamp=2, transactions=3),
        Agg(open=1, high=2, low=0.5, close=1.0, volume=10, vwap=1.2, timestamp=1, transactions=3),
    ]
    provider, client = _polygon_provider(aggs)

    history = provider.get_history(["SPY"], "2hour", "2024-01-01", "2024-01-31")["SPY"]

    assert client.calls[0]["multiplier"] == 2
    assert client.calls[0]["timespan"] == "hour"
    assert history.columns == OHLCV_COLUMNS
    assert history["timestamp"].to_list() == [1, 2]


def test_polygon_empty_response_raises():
    provider, _ = _polygon_provider([])

    with pytest.raises(ValueError, match="No data returned for SPY"):
        provider.get_history(["SPY"], "day", "2024-01-01", "2024-01-31")
