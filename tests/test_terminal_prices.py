import datetime as dt
from pathlib import Path

import polars as pl
import pytest
from terminal_fixtures import FakeClock, FakePrices, price_frame

from terminal.errors import DataUnavailableError, UpstreamError
from terminal.prices import PriceService, bars, slice_range, snapshot
from terminal.store import TerminalStore


@pytest.fixture
def setup(tmp_path: Path):
    clock = FakeClock()
    provider = FakePrices(clock)
    store = TerminalStore(f"sqlite:///{tmp_path / 'terminal.sqlite3'}")
    service = PriceService(
        store, tmp_path, provider_name="yfinance", provider_factory=lambda: provider, clock=clock
    )
    yield clock, provider, store, service
    store.close()


def test_history_is_fetched_once_then_served_from_disk(setup, tmp_path: Path):
    clock, provider, store, service = setup

    history, source = service.history("cost")
    assert history.columns == ["timestamp", "open", "high", "low", "close", "volume"]
    ten_years_back = (clock.now.date() - dt.timedelta(days=3660)).isoformat()
    assert provider.calls == [(["COST"], "day", ten_years_back, "2026-11-17")]
    assert source.to_dict() == {
        "id": "prices-yfinance-COST-day",
        "provider": "Yahoo Finance (yfinance)",
        "url": "https://finance.yahoo.com/quote/COST/history",
        "retrieved_at": clock.now.isoformat(),
        "stale": False,
        "error": None,
        "note": source.note,
    }
    assert "Not real-time" in (source.note or "")
    assert (tmp_path / "prices" / "yfinance" / "COST-day.parquet").is_file()

    clock.advance(minutes=29)
    again, cached = service.history("COST")
    assert again.equals(history) and cached.retrieved_at == source.retrieved_at
    assert len(provider.calls) == 1

    clock.advance(minutes=2)
    _, refreshed = service.history("COST")
    assert len(provider.calls) == 2 and refreshed.retrieved_at == clock.now
    service.history("COST", refresh=True)
    assert len(provider.calls) == 3
    assert store.get_fetch("prices-yfinance-COST-day") is not None


def test_failed_refresh_keeps_last_good_prices_and_says_so(setup):
    clock, provider, store, service = setup
    history, first = service.history("COST")

    clock.advance(hours=3)
    provider.error = ConnectionError("yahoo is down")
    again, stale = service.history("COST")
    assert again.equals(history)
    assert stale.stale and stale.retrieved_at == first.retrieved_at
    assert stale.error == "ConnectionError: yahoo is down"
    record = store.get_fetch("prices-yfinance-COST-day")
    assert record is not None and record.last_error == stale.error

    # The provider is left alone for a minute, then tried again.
    attempts = len(provider.calls)
    assert service.history("COST")[1].stale and len(provider.calls) == attempts
    clock.advance(seconds=61)
    provider.error = None
    assert not service.history("COST")[1].stale and len(provider.calls) == attempts + 1


def test_no_cached_prices_means_an_error_not_a_placeholder(setup):
    _clock, provider, _store, service = setup

    provider.error = ValueError("No data returned for NOPE from yfinance")
    with pytest.raises(DataUnavailableError, match="No usable price history"):
        service.history("NOPE")
    provider.error = ConnectionError("offline")
    with pytest.raises(UpstreamError, match="offline"):
        service.history("NOPE")


def test_empty_or_malformed_provider_output_is_rejected(tmp_path: Path):
    class Empty(FakePrices):
        def get_history(self, tickers, timespan, from_time, to_time):
            return {ticker: price_frame(dt.date(2026, 11, 17), days=0) for ticker in tickers}

    class MissingColumns(FakePrices):
        def get_history(self, tickers, timespan, from_time, to_time):
            return {ticker: pl.DataFrame({"timestamp": [1], "close": [1.0]}) for ticker in tickers}

    clock = FakeClock()
    store = TerminalStore(f"sqlite:///{tmp_path / 'terminal.sqlite3'}")
    for provider in (Empty(clock), MissingColumns(clock)):
        service = PriceService(
            store, tmp_path, provider_name="polygon", provider_factory=lambda p=provider: p
        )
        with pytest.raises(DataUnavailableError):
            service.history("COST")
    store.close()


def test_default_provider_comes_from_the_shared_data_package(tmp_path: Path, monkeypatch):
    clock = FakeClock()
    built = []

    def create(name, **kwargs):
        built.append((name, kwargs))
        return FakePrices(clock)

    monkeypatch.setattr("data.factory.create_data_provider", create)
    store = TerminalStore(f"sqlite:///{tmp_path / 'terminal.sqlite3'}")
    service = PriceService(store, tmp_path, provider_name="polygon", clock=clock)
    _, source = service.history("COST")
    assert built == [("polygon", {"cache_dir": None, "validate": True})]
    assert (source.provider, source.url) == ("Polygon.io", "https://polygon.io")
    store.close()


def test_snapshot_and_ranges_are_computed_from_the_bars():
    end = dt.date(2026, 11, 17)
    history = price_frame(end, days=800, start_price=100.0)

    snap = snapshot(history)
    assert snap is not None
    assert snap["last_close"] == 899.0 and snap["last_close_date"] == "2026-11-17"
    assert snap["previous_close"] == 898.0
    assert snap["change"] == 1.0
    assert snap["change_percent"] == pytest.approx(100 / 898)
    # 52-week window is the trailing 366 days of daily highs and lows.
    assert snap["week_52_high"] == 901.0
    assert snap["week_52_low"] == 899.0 - 366 - 3

    assert slice_range(history, "1m", end).height == 32
    assert slice_range(history, "max", end).height == 800
    first = bars(slice_range(history, "1m", end))[0]
    assert first == {
        "date": "2026-10-17", "open": 867.0, "high": 870.0, "low": 865.0,
        "close": 868.0, "volume": 1_000_000.0,
    }

    assert snapshot(history.head(0)) is None
    single = snapshot(history.head(1))
    assert single is not None and single["previous_close"] is None and single["change"] is None
