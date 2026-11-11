from __future__ import annotations

import datetime as dt
import importlib
import logging
from abc import ABC, abstractmethod

import polars as pl

from data.schema import normalize_ohlcv
from data.validation import raise_for_errors, validate_histories

logger = logging.getLogger(__name__)


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
    # Short identifier used for cache folders and run metadata.
    name: str = "provider"

    @abstractmethod
    def get_history(
        self,
        tickers: list[str],
        timespan: str,
        from_time: str,
        to_time: str,
    ) -> dict[str, pl.DataFrame]:
        """
        Fetch history for each ticker, with `to_time` inclusive.

        Each frame follows `data.schema.OHLCV_SCHEMA`.
        """


class PolygonDataProvider(DataProvider):
    name = "polygon"

    def __init__(self, api_key: str):
        try:
            polygon = importlib.import_module("polygon")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "Polygon support requires: python -m pip install polygon-api-client"
            ) from exc
        self._client = polygon.RESTClient(api_key)

    def get_history(
        self,
        tickers: list[str],
        timespan: str,
        from_time: str,
        to_time: str,
    ) -> dict[str, pl.DataFrame]:
        multiplier, polygon_timespan = _polygon_timespan(timespan)
        histories: dict[str, pl.DataFrame] = {}

        for ticker in tickers:
            # list_aggs follows pagination; get_aggs stops at the first page.
            aggs = list(
                self._client.list_aggs(
                    ticker=ticker,
                    multiplier=multiplier,
                    timespan=polygon_timespan,
                    from_=from_time,
                    to=to_time,
                    limit=50000,
                )
            )
            if not aggs:
                raise ValueError(f"No data returned for {ticker} from polygon")
            histories[ticker] = normalize_ohlcv(pl.DataFrame(aggs))

        return histories


def _resample_two_hour(df, timestamp_col: str):
    return (
        df.set_index(timestamp_col)
        .resample("2h")
        .agg(
            {
                "Open": "first",
                "High": "max",
                "Low": "min",
                "Close": "last",
                "Volume": "sum",
            }
        )
        .dropna(subset=["Close"])
        .reset_index()
    )


class YFinanceDataProvider(DataProvider):
    """Alternative provider to make data source swapping explicit and easy."""

    name = "yfinance"

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
                "yfinance is required for YFinanceDataProvider. "
                "Install with `pip install yfinance`."
            ) from exc

        interval = _yfinance_interval(timespan)
        # yfinance treats `end` as exclusive; shift it so `to_time` is included
        # the same way it is for Polygon.
        end = (dt.date.fromisoformat(to_time) + dt.timedelta(days=1)).isoformat()

        histories: dict[str, pl.DataFrame] = {}
        for ticker in tickers:
            df = yf.download(
                ticker,
                start=from_time,
                end=end,
                interval=interval,
                auto_adjust=False,
                progress=False,
            )
            if df is None or df.empty:
                raise ValueError(f"No data returned for {ticker} from yfinance")

            df = df.reset_index()
            df.columns = _flatten_yfinance_columns(df.columns)
            timestamp_col = "Datetime" if "Datetime" in df.columns else "Date"
            if timespan == "2hour":
                df = _resample_two_hour(df, timestamp_col)

            histories[ticker] = normalize_ohlcv(
                pl.DataFrame(
                    {
                        "timestamp": (
                            pl.from_pandas(df[timestamp_col])
                            .dt.epoch(time_unit="ms")
                            .cast(pl.Int64)
                        ),
                        "open": pl.from_pandas(df["Open"]),
                        "high": pl.from_pandas(df["High"]),
                        "low": pl.from_pandas(df["Low"]),
                        "close": pl.from_pandas(df["Close"]),
                        "volume": pl.from_pandas(df["Volume"]),
                    }
                )
            )

        return histories


class ValidatedDataProvider(DataProvider):
    """Run data-quality checks on every fetch; errors raise, warnings log."""

    def __init__(self, provider: DataProvider):
        self._provider = provider
        self.name = provider.name

    def get_history(
        self,
        tickers: list[str],
        timespan: str,
        from_time: str,
        to_time: str,
    ) -> dict[str, pl.DataFrame]:
        histories = self._provider.get_history(tickers, timespan, from_time, to_time)
        issues = validate_histories(histories, timespan)
        for issue in issues:
            if issue.severity == "warning":
                logger.warning("%s", issue)
        raise_for_errors(issues)
        return histories
