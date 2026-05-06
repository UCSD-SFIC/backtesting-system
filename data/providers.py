from __future__ import annotations

from abc import ABC, abstractmethod
import os

import polars as pl


class DataProvider(ABC):
    @abstractmethod
    def get_history(
        self,
        tickers: list[str],
        timespan: str,
        from_time: str,
        to_time: str,
    ) -> dict[str, pl.DataFrame]:
        """Fetch historical OHLCV-like records for each ticker."""


class PolygonDataProvider(DataProvider):
    def __init__(self, api_key: str, cache_dir: str = "history_cache"):
        from polygon import RESTClient

        self._client = RESTClient(api_key)
        self._cache_dir = cache_dir

    def get_history(
        self,
        tickers: list[str],
        timespan: str,
        from_time: str,
        to_time: str,
    ) -> dict[str, pl.DataFrame]:
        histories: dict[str, pl.DataFrame] = {}

        for ticker in tickers:
            path = os.path.join(
                self._cache_dir,
                f"{ticker}-{timespan}-{from_time}-{to_time}.parquet",
            )
            try:
                histories[ticker] = pl.read_parquet(path)
            except FileNotFoundError:
                print(f"Downloading {ticker} data")
                aggs = self._client.get_aggs(
                    ticker=ticker,
                    multiplier=1,
                    timespan=timespan,
                    from_=from_time,
                    to=to_time,
                )
                df = pl.DataFrame(aggs)
                if not os.path.exists(self._cache_dir):
                    os.makedirs(self._cache_dir)
                df.write_parquet(path)
                histories[ticker] = df

        return histories


class YFinanceDataProvider(DataProvider):
    """Alternative provider to make data source swapping explicit and easy."""

    def get_history(
        self,
        tickers: list[str],
        timespan: str,
        from_time: str,
        to_time: str,
    ) -> dict[str, pl.DataFrame]:
        try:
            import yfinance as yf
        except ImportError as exc:
            raise ImportError(
                "yfinance is required for YFinanceDataProvider. Install with `pip install yfinance`."
            ) from exc

        interval_map = {
            "minute": "1m",
            "hour": "1h",
            "day": "1d",
            "week": "1wk",
            "month": "1mo",
        }
        interval = interval_map.get(timespan, "1d")

        histories: dict[str, pl.DataFrame] = {}
        for ticker in tickers:
            df = yf.download(
                ticker,
                start=from_time,
                end=to_time,
                interval=interval,
                auto_adjust=False,
                progress=False,
            )
            if df.empty:
                raise ValueError(f"No data returned for {ticker} from yfinance")

            df = df.reset_index()
            timestamp_col = "Datetime" if "Datetime" in df.columns else "Date"

            histories[ticker] = pl.DataFrame(
                {
                    "timestamp": (
                        pl.from_pandas(df[timestamp_col])
                        .dt.epoch(time_unit="ms")
                        .cast(pl.Int64)
                    ),
                    "close": pl.from_pandas(df["Close"]).cast(pl.Float64),
                }
            )

        return histories
