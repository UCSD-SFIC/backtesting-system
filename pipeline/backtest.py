from __future__ import annotations

from typing import Optional

import polars as pl

from analytics.metrics import summarize_performance
from data.providers import DataProvider
from engine.backtest_engine import BacktestEngine
from engine.history import combine_ticker_histories
from engine.weights import build_weight_frame
from strategy.alpha import Alpha
from visualization.plots import plot_backtest as _plot_backtest


def fetch_history(
    data_provider: DataProvider,
    tickers: list[str],
    timespan: str,
    from_time: str,
    to_time: str,
) -> dict[str, pl.DataFrame]:
    engine = BacktestEngine(data_provider)
    return engine.fetch_history(tickers, timespan, from_time, to_time)


def backtest(history: pl.DataFrame, weights: pl.DataFrame, tickers: list[str]) -> pl.DataFrame:
    return BacktestEngine(data_provider=None).run_portfolio_backtest(history, weights, tickers)


def load_weight(alpha: Alpha, combined_history: pl.DataFrame) -> pl.DataFrame:
    return build_weight_frame(alpha, combined_history)


def run_backtest(
    data_provider: DataProvider,
    alpha: Alpha,
    timespan: str,
    from_time: str,
    to_time: str,
) -> pl.DataFrame:
    engine = BacktestEngine(data_provider)
    return engine.run(alpha=alpha, timespan=timespan, from_time=from_time, to_time=to_time)


def summarize_backtest(
    backtest_df: pl.DataFrame,
    risk_free_rate: float = 0.02,
    benchmark_ticker: Optional[str] = None,
) -> dict[str, float]:
    return summarize_performance(
        backtest_df,
        risk_free_rate=risk_free_rate,
        benchmark_ticker=benchmark_ticker,
    )


def plot_backtest(
    backtest_df: pl.DataFrame,
    tickers: Optional[list[str]] = None,
    show_components: bool = True,
) -> None:
    _plot_backtest(backtest_df, tickers or [], show_components=show_components)
