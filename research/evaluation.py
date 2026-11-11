"""Offline walk-forward selection for causal allocation strategy candidates.

Candidate strategies are fixed before evaluation. Each fold ranks them using
only its training bars, then records the chosen candidate's following test bars.
"""

from __future__ import annotations

import datetime as dt
import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

import polars as pl

from data.providers import DataProvider
from engine.backtest_engine import BacktestEngine
from research.walk_forward import (
    FoldResult,
    WalkForwardWindow,
    make_walk_forward_windows,
    summarize_out_of_sample,
)
from strategy.allocation_alpha import AllocationAlpha


@dataclass(frozen=True)
class EvaluatedFold:
    window: WalkForwardWindow
    selected: str
    train_return: float
    test_return: float
    test_returns: tuple[float, ...]


@dataclass(frozen=True)
class WalkForwardEvaluation:
    folds: tuple[EvaluatedFold, ...]
    summary: dict[str, float | int]
    candidate_summary: pl.DataFrame


def _compound(returns: tuple[float, ...]) -> float:
    growth = 1.0
    for value in returns:
        growth *= 1.0 + value
    return growth - 1.0


def evaluate_candidate_returns(
    returns: pl.DataFrame, train_size: int, test_size: int
) -> WalkForwardEvaluation:
    """Choose the best in-sample candidate per fold and evaluate it out of sample.

    The input is dated simple returns from predeclared causal strategies. Each
    row is one common observation, and columns after ``date`` are candidates.
    Cash costs and benchmark comparison belong in the candidate simulations.
    """
    if "date" not in returns.columns or returns.width < 2:
        raise ValueError("returns needs a date and at least one candidate column")
    dates = returns["date"].to_list()
    if not dates or any(not isinstance(value, dt.date) for value in dates):
        raise ValueError("returns date column must contain dates")
    candidates = sorted(column for column in returns.columns if column != "date")
    values: dict[str, tuple[float, ...]] = {}
    for candidate in candidates:
        series = returns[candidate].to_list()
        if any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value < -1.0
            for value in series
        ):
            raise ValueError(f"returns for {candidate} must be finite and >= -1")
        values[candidate] = tuple(float(value) for value in series)
    windows = make_walk_forward_windows(dates, train_size, test_size)
    if not windows:
        raise ValueError("returns do not contain a complete train/test window")

    selected_folds: list[EvaluatedFold] = []
    candidate_folds: list[FoldResult] = []
    for window in windows:
        training = {
            candidate: _compound(values[candidate][window.train_start : window.train_stop])
            for candidate in candidates
        }
        # Sorted names make a tied training score deterministic.
        selected = max(candidates, key=lambda candidate: training[candidate])
        test_returns = values[selected][window.test_start : window.test_stop]
        selected_folds.append(
            EvaluatedFold(
                window, selected, training[selected], _compound(test_returns), test_returns
            )
        )
        candidate_folds.extend(
            FoldResult(candidate, window, values[candidate][window.test_start : window.test_stop])
            for candidate in candidates
        )
    chosen = summarize_out_of_sample(
        [FoldResult("selected", fold.window, fold.test_returns) for fold in selected_folds]
    )
    summary = chosen.row(0, named=True)
    return WalkForwardEvaluation(
        tuple(selected_folds), summary, summarize_out_of_sample(candidate_folds)
    )


class _OfflineProvider(DataProvider):
    def __init__(self, histories: Mapping[str, pl.DataFrame]):
        self._histories = histories

    def get_history(
        self, tickers: list[str], timespan: str, from_time: str, to_time: str
    ) -> dict[str, pl.DataFrame]:
        if timespan != "day":
            raise ValueError("offline allocation evaluation currently requires daily bars")
        start_ms = int(
            dt.datetime.combine(
                dt.date.fromisoformat(from_time), dt.time(), dt.timezone.utc
            ).timestamp()
            * 1000
        )
        # Date endpoints are inclusive, like the online providers.
        end_ms = int(
            dt.datetime.combine(
                dt.date.fromisoformat(to_time) + dt.timedelta(days=1),
                dt.time(),
                dt.timezone.utc,
            ).timestamp()
            * 1000
        )
        result = {}
        for ticker in tickers:
            if ticker not in self._histories:
                raise ValueError(f"missing history for {ticker}")
            frame = self._histories[ticker]
            if not {"timestamp", "close"} <= set(frame.columns):
                raise ValueError(f"history for {ticker} needs timestamp and close")
            result[ticker] = frame.filter(
                (pl.col("timestamp") >= start_ms) & (pl.col("timestamp") < end_ms)
            )
            if result[ticker].is_empty():
                raise ValueError(f"no history for {ticker} in requested dates")
        return result


def run_allocation_candidates(
    histories: Mapping[str, pl.DataFrame],
    candidates: Mapping[str, dict],
    *,
    start: dt.date,
    end: dt.date,
    investable: list[str] | None = None,
    benchmark: str | None = None,
    cost_bps: float = 0.0,
) -> pl.DataFrame:
    """Run predeclared allocation candidates against the same offline daily data."""
    if not candidates or end <= start:
        raise ValueError("candidates and an increasing date range are required")
    if not histories:
        raise ValueError("histories cannot be empty")
    assets = investable or [ticker for ticker in histories if ticker != benchmark]
    if not assets:
        raise ValueError("investable universe cannot be empty")
    provider = _OfflineProvider(histories)
    if any(frame.is_empty() or "timestamp" not in frame.columns for frame in histories.values()):
        raise ValueError("histories need nonempty timestamp columns")
    earliest = min(cast(int, frame["timestamp"].min()) for frame in histories.values())
    from_date = dt.datetime.fromtimestamp(earliest / 1000, tz=dt.timezone.utc).date().isoformat()
    table: pl.DataFrame | None = None
    for name, params in sorted(candidates.items()):
        if not name or "benchmark" in params:
            raise ValueError("candidate names must be nonempty; benchmark is a shared option")
        alpha = AllocationAlpha(
            "US",
            "day",
            assets,
            start.isoformat(),
            end.isoformat(),
            benchmark=benchmark,
            **params,
        )
        result = BacktestEngine(provider, cost_bps=cost_bps).run(
            alpha, "day", from_date, end.isoformat()
        )
        candidate_frame = result.select(
            pl.col("timestamp").dt.date().alias("date"),
            pl.col("overall_growth")
            .pct_change()
            .fill_null(pl.col("overall_growth") - 1)
            .alias(name),
        )
        table = (
            candidate_frame
            if table is None
            else table.join(candidate_frame, on="date", how="inner")
        )
    if table is None or table.is_empty():
        raise ValueError("candidates have no common simulated dates")
    return table.sort("date")


def evaluate_allocation_walk_forward(
    histories: Mapping[str, pl.DataFrame],
    candidates: Mapping[str, dict],
    *,
    start: dt.date,
    end: dt.date,
    train_size: int,
    test_size: int,
    investable: list[str] | None = None,
    benchmark: str | None = None,
    cost_bps: float = 0.0,
) -> WalkForwardEvaluation:
    """Simulate all candidates causally, then select using rolling training folds."""
    returns = run_allocation_candidates(
        histories,
        candidates,
        start=start,
        end=end,
        investable=investable,
        benchmark=benchmark,
        cost_bps=cost_bps,
    )
    return evaluate_candidate_returns(returns, train_size, test_size)
