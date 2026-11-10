from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

from data.cache import CachedDataProvider
from data.providers import DataProvider, ValidatedDataProvider
from data.validation import DataValidationError

# Tests for the provider-agnostic parquet cache and validation wrappers.


class FakeProvider(DataProvider):
    name = "fake"

    def __init__(self, close: float = 10.0):
        self.calls: list[list[str]] = []
        self.close = close

    def get_history(self, tickers, timespan, from_time, to_time):
        self.calls.append(list(tickers))
        return {
            ticker: pl.DataFrame(
                {
                    "timestamp": [1704171600000],
                    "open": [self.close],
                    "high": [self.close],
                    "low": [self.close],
                    "close": [self.close],
                    "volume": [100.0],
                }
            )
            for ticker in tickers
        }


TODAY = dt.date(2026, 11, 3)


def test_cache_reads_back_without_calling_provider(tmp_path):
    inner = FakeProvider()
    provider = CachedDataProvider(inner, tmp_path, today=TODAY)

    first = provider.get_history(["A", "B"], "day", "2024-01-01", "2024-12-31")
    second = provider.get_history(["A", "B"], "day", "2024-01-01", "2024-12-31")

    assert inner.calls == [["A", "B"]]
    assert first["A"].equals(second["A"])
    assert (tmp_path / "fake" / "A-day-2024-01-01-2024-12-31.parquet").exists()


def test_cache_only_fetches_missing_tickers_and_keeps_order(tmp_path):
    inner = FakeProvider()
    provider = CachedDataProvider(inner, tmp_path, today=TODAY)
    provider.get_history(["B"], "day", "2024-01-01", "2024-12-31")

    result = provider.get_history(["A", "B"], "day", "2024-01-01", "2024-12-31")

    assert inner.calls == [["B"], ["A"]]
    assert list(result) == ["A", "B"]


def test_cache_skips_ranges_that_are_still_open(tmp_path):
    inner = FakeProvider()
    provider = CachedDataProvider(inner, tmp_path, today=TODAY)

    provider.get_history(["A"], "day", "2026-01-01", TODAY.isoformat())
    provider.get_history(["A"], "day", "2026-01-01", TODAY.isoformat())

    assert len(inner.calls) == 2
    assert not (tmp_path / "fake").exists()


def test_refresh_ignores_existing_cache(tmp_path):
    inner = FakeProvider()
    CachedDataProvider(inner, tmp_path, today=TODAY).get_history(
        ["A"], "day", "2024-01-01", "2024-12-31"
    )

    CachedDataProvider(inner, tmp_path, refresh=True, today=TODAY).get_history(
        ["A"], "day", "2024-01-01", "2024-12-31"
    )

    assert len(inner.calls) == 2


def test_cache_path_sanitizes_ticker(tmp_path):
    provider = CachedDataProvider(FakeProvider(), tmp_path)

    path = provider.cache_path("BTC/USD", "day", "2024-01-01", "2024-12-31")

    assert path.parent == tmp_path / "fake"
    assert path.name == "BTC_USD-day-2024-01-01-2024-12-31.parquet"


def test_invalid_data_raises_and_is_not_cached(tmp_path):
    inner = FakeProvider(close=-1.0)
    provider = CachedDataProvider(ValidatedDataProvider(inner), tmp_path, today=TODAY)

    with pytest.raises(DataValidationError, match="non_positive_price"):
        provider.get_history(["A"], "day", "2024-01-01", "2024-12-31")

    assert not (tmp_path / "fake").exists()
