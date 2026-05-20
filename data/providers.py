from __future__ import annotations

from abc import ABC, abstractmethod
import os

import polars as pl


def _polygon_timespan(timespan: str) -> tuple[int, str]:
    timespan_map = {
        "minute": (1, "minute"),
        "hour": (1, "hour"),
        "2hour": (2, "hour"),
        "day": (1, "day"),
        "week": (1, "week"),
        "month": (1, "month"),
    }
    return timespan_map.get(timespan, (1, timespan))


def _yfinance_interval(timespan: str) -> str:
    interval_map = {
        "minute": "1m",
        "hour": "1h",
        "2hour": "1h",
        "day": "1d",
        "week": "1wk",
        "month": "1mo",
    }
    return interval_map.get(timespan, "1d")


def _flatten_yfinance_columns(columns) -> list[str]:
    flattened_columns: list[str] = []
    for column in columns:
        if isinstance(column, tuple):
            flattened_columns.append(str(next(part for part in column if part)))
        else:
            flattened_columns.append(str(column))
    return flattened_columns


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
                multiplier, polygon_timespan = _polygon_timespan(timespan)
                aggs = self._client.get_aggs(
                    ticker=ticker,
                    multiplier=multiplier,
                    timespan=polygon_timespan,
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

        interval = _yfinance_interval(timespan)

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
            df.columns = _flatten_yfinance_columns(df.columns)
            timestamp_col = "Datetime" if "Datetime" in df.columns else "Date"
            if timespan == "2hour":
                df = (
                    df.resample("2h", on=timestamp_col)
                    .last()
                    .dropna(subset=["Close"])
                    .reset_index()
                )

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
