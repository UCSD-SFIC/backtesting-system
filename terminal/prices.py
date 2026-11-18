"""Daily price history for the terminal, built on the existing `data` providers.

This does not fetch prices itself. It asks the shared `data.DataProvider`
(yfinance by default, Polygon optional) for one long daily window per ticker,
keeps it as Parquet, and refreshes it when the TTL passes. Charts, the price
snapshot, and anything else that needs prices should read from here.
"""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Callable
from pathlib import Path
from typing import Any

import polars as pl

from data.providers import DataProvider
from data.schema import normalize_ohlcv
from terminal.cache import STALE_RETRY, Clock, KeyedLocks, SourceInfo, safe_name, utc_now
from terminal.errors import DataUnavailableError, UpstreamError
from terminal.store import TerminalStore

logger = logging.getLogger(__name__)

ProviderFactory = Callable[[], DataProvider]

PROVIDER_LABELS = {
    "yfinance": "Yahoo Finance (yfinance)",
    "polygon": "Polygon.io",
}
PROVIDER_NOTES = {
    "yfinance": (
        "Unofficial Yahoo Finance feed. Daily bars; close is adjusted for splits "
        "but not dividends. Not real-time."
    ),
    "polygon": "Daily aggregate bars from Polygon.io. Not real-time.",
}

RANGE_DAYS: dict[str, int | None] = {
    "1m": 31,
    "3m": 92,
    "6m": 183,
    "1y": 366,
    "3y": 3 * 366,
    "5y": 5 * 366,
    "max": None,
}


def _default_factory(provider_name: str) -> ProviderFactory:
    def build() -> DataProvider:
        from data.factory import create_data_provider

        # The terminal keeps its own refreshable copy, so skip the range cache.
        return create_data_provider(provider_name, cache_dir=None, validate=True)

    return build


def bar_date(timestamp_ms: int) -> dt.date:
    return dt.datetime.fromtimestamp(timestamp_ms / 1000, tz=dt.timezone.utc).date()


def slice_range(history: pl.DataFrame, range_name: str, today: dt.date) -> pl.DataFrame:
    days = RANGE_DAYS[range_name]
    if days is None:
        return history
    start = dt.datetime.combine(
        today - dt.timedelta(days=days), dt.time.min, tzinfo=dt.timezone.utc
    )
    return history.filter(pl.col("timestamp") >= int(start.timestamp() * 1000))


def bars(history: pl.DataFrame) -> list[dict[str, Any]]:
    return [
        {
            "date": bar_date(row["timestamp"]).isoformat(),
            "open": row["open"],
            "high": row["high"],
            "low": row["low"],
            "close": row["close"],
            "volume": row["volume"],
        }
        for row in history.iter_rows(named=True)
    ]


def snapshot(history: pl.DataFrame) -> dict[str, Any] | None:
    """Last close and simple context computed only from the bars we hold."""
    if history.is_empty():
        return None
    last = history.row(-1, named=True)
    last_date = bar_date(last["timestamp"])
    result: dict[str, Any] = {
        "last_close": last["close"],
        "last_close_date": last_date.isoformat(),
        "previous_close": None,
        "change": None,
        "change_percent": None,
        "week_52_high": None,
        "week_52_low": None,
    }
    if history.height >= 2:
        previous = history.row(-2, named=True)["close"]
        result["previous_close"] = previous
        if previous:
            result["change"] = last["close"] - previous
            result["change_percent"] = (last["close"] / previous - 1) * 100
    year = slice_range(history, "1y", last_date)
    highs, lows = year["high"].drop_nulls(), year["low"].drop_nulls()
    if highs.len() and lows.len():
        result["week_52_high"] = highs.max()
        result["week_52_low"] = lows.min()
    return result


class PriceService:
    def __init__(
        self,
        store: TerminalStore,
        data_dir: Path,
        *,
        provider_name: str = "yfinance",
        provider_factory: ProviderFactory | None = None,
        ttl: dt.timedelta = dt.timedelta(minutes=30),
        history_years: int = 10,
        clock: Clock = utc_now,
    ):
        self._store = store
        self._root = Path(data_dir) / "prices" / safe_name(provider_name)
        self._provider_name = provider_name
        self._factory = provider_factory or _default_factory(provider_name)
        self._ttl = ttl
        self._history_years = history_years
        self._clock = clock
        self._locks = KeyedLocks()

    def _source(
        self, source_id: str, ticker: str, retrieved_at: dt.datetime, **extra: Any
    ) -> SourceInfo:
        url = (
            f"https://finance.yahoo.com/quote/{ticker}/history"
            if self._provider_name == "yfinance"
            else "https://polygon.io"
        )
        return SourceInfo(
            source_id,
            PROVIDER_LABELS.get(self._provider_name, self._provider_name),
            url,
            retrieved_at,
            note=PROVIDER_NOTES.get(self._provider_name),
            **extra,
        )

    def history(self, ticker: str, *, refresh: bool = False) -> tuple[pl.DataFrame, SourceInfo]:
        """Daily OHLCV for `ticker` (shared `data.schema` columns), oldest first."""
        ticker = ticker.upper()
        source_id = f"prices-{self._provider_name}-{ticker}-day"
        with self._locks.get(source_id):
            path = self._root / f"{safe_name(ticker)}-day.parquet"
            record = self._store.get_fetch(source_id)
            cached = record is not None and path.is_file()
            now = self._clock()

            if cached and record is not None and not refresh:
                if now - record.fetched_at < self._ttl:
                    return pl.read_parquet(path), self._source(
                        source_id, ticker, record.fetched_at
                    )
                if record.last_error_at is not None and now - record.last_error_at < STALE_RETRY:
                    return pl.read_parquet(path), self._source(
                        source_id, ticker, record.fetched_at, stale=True, error=record.last_error
                    )

            today = now.date()
            start = today - dt.timedelta(days=366 * self._history_years)
            try:
                provider = self._factory()
                fetched = provider.get_history(
                    [ticker], "day", start.isoformat(), today.isoformat()
                )
                history = normalize_ohlcv(fetched[ticker])
                if history.is_empty():
                    raise ValueError(f"No data returned for {ticker}")
            except Exception as exc:  # providers raise many unrelated error types
                message = f"{type(exc).__name__}: {exc}"
                if cached and record is not None:
                    logger.warning("Price refresh for %s failed, using cache: %s", ticker, message)
                    self._store.record_fetch_error(source_id, message, now)
                    return pl.read_parquet(path), self._source(
                        source_id, ticker, record.fetched_at, stale=True, error=message
                    )
                if isinstance(exc, (ValueError, KeyError)):
                    raise DataUnavailableError(
                        f"No usable price history for {ticker} from {self._provider_name}: {exc}"
                    ) from exc
                raise UpstreamError(
                    f"Price provider {self._provider_name} failed for {ticker}: {message}"
                ) from exc

            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            history.write_parquet(temporary)
            temporary.replace(path)
            self._store.record_fetch(
                source_id,
                provider=self._provider_name,
                url=self._source(source_id, ticker, now).url,
                fetched_at=now,
                payload_path=str(path),
            )
            return history, self._source(source_id, ticker, now)
