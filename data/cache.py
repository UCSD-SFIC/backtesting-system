from __future__ import annotations

import datetime as dt
import logging
from pathlib import Path
from typing import Optional

import polars as pl

from data.providers import DataProvider


logger = logging.getLogger(__name__)


def _safe_filename_part(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_.^" else "_" for char in value)


class CachedDataProvider(DataProvider):
    """
    Parquet cache that works the same way for every provider.

    Files live at `<cache_dir>/<provider name>/<ticker>-<timespan>-<from>-<to>.parquet`.
    A range that ends today or later is still changing, so it is fetched but
    not cached. Pass `refresh=True` to ignore and overwrite existing files.
    """

    def __init__(
        self,
        provider: DataProvider,
        cache_dir: str | Path = "history_cache",
        refresh: bool = False,
        today: Optional[dt.date] = None,
    ):
        self._provider = provider
        self.name = provider.name
        self._cache_dir = Path(cache_dir) / _safe_filename_part(provider.name)
        self._refresh = refresh
        self._today = today

    def cache_path(self, ticker: str, timespan: str, from_time: str, to_time: str) -> Path:
        filename = "-".join(
            _safe_filename_part(part) for part in [ticker, timespan, from_time, to_time]
        )
        return self._cache_dir / f"{filename}.parquet"

    def _is_cacheable(self, to_time: str) -> bool:
        today = self._today or dt.date.today()
        return dt.date.fromisoformat(to_time) < today

    def get_history(
        self,
        tickers: list[str],
        timespan: str,
        from_time: str,
        to_time: str,
    ) -> dict[str, pl.DataFrame]:
        histories: dict[str, pl.DataFrame] = {}
        missing: list[str] = []

        for ticker in tickers:
            path = self.cache_path(ticker, timespan, from_time, to_time)
            if not self._refresh and path.exists():
                histories[ticker] = pl.read_parquet(path)
            else:
                missing.append(ticker)

        if missing:
            logger.info("Fetching %s from %s", ", ".join(missing), self.name)
            fetched = self._provider.get_history(missing, timespan, from_time, to_time)
            if self._is_cacheable(to_time):
                self._cache_dir.mkdir(parents=True, exist_ok=True)
                for ticker, history in fetched.items():
                    history.write_parquet(
                        self.cache_path(ticker, timespan, from_time, to_time)
                    )
            histories.update(fetched)

        return {ticker: histories[ticker] for ticker in tickers}
