"""Chronological walk-forward windows and out-of-sample result summaries."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

import polars as pl


@dataclass(frozen=True)
class WalkForwardWindow:
    train_start: int
    train_stop: int
    test_start: int
    test_stop: int
    train_begin: date
    train_end: date
    test_begin: date
    test_end: date


@dataclass(frozen=True)
class FoldResult:
    strategy: str
    window: WalkForwardWindow
    test_returns: tuple[float, ...]


def make_walk_forward_windows(
    dates: Sequence[date],
    train_size: int,
    test_size: int,
    step_size: int | None = None,
) -> list[WalkForwardWindow]:
    """Create rolling windows; all ranges use stop-exclusive indices.

    The default step equals the test size, so each test observation appears in
    exactly one fold. Training windows may overlap, as rolling research needs.
    """
    if train_size <= 0 or test_size <= 0:
        raise ValueError("train_size and test_size must be positive")
    step = test_size if step_size is None else step_size
    if step < test_size:
        raise ValueError("step_size must be at least test_size to avoid overlapping tests")
    if any(left >= right for left, right in zip(dates, dates[1:], strict=False)):
        raise ValueError("dates must be strictly increasing and unique")
    windows = []
    for start in range(0, len(dates) - train_size - test_size + 1, step):
        train_stop = start + train_size
        test_stop = train_stop + test_size
        windows.append(
            WalkForwardWindow(
                train_start=start,
                train_stop=train_stop,
                test_start=train_stop,
                test_stop=test_stop,
                train_begin=dates[start],
                train_end=dates[train_stop - 1],
                test_begin=dates[train_stop],
                test_end=dates[test_stop - 1],
            )
        )
    return windows


def summarize_out_of_sample(folds: Sequence[FoldResult]) -> pl.DataFrame:
    """Summarize supplied test returns; this never accesses training returns.

    Candidate parameter fitting and selection must happen using the train slice
    before constructing a FoldResult. Results are research evidence, not a
    forecast of future portfolio behavior.
    """
    grouped: dict[str, list[FoldResult]] = defaultdict(list)
    for fold in folds:
        if not fold.strategy:
            raise ValueError("strategy name is required")
        if len(fold.test_returns) != fold.window.test_stop - fold.window.test_start:
            raise ValueError("test_returns length must equal the window test_size")
        if any(not math.isfinite(value) or value < -1 for value in fold.test_returns):
            raise ValueError("each test return must be finite and at least -1")
        grouped[fold.strategy].append(fold)

    rows = []
    for strategy, group in grouped.items():
        ordered = sorted(group, key=lambda fold: fold.window.test_begin)
        if any(
            previous.window.test_end >= current.window.test_begin
            for previous, current in zip(ordered, ordered[1:], strict=False)
        ):
            raise ValueError(f"{strategy}: test windows overlap")
        growth = 1.0
        peak = 1.0
        drawdown = 0.0
        for fold in ordered:
            for value in fold.test_returns:
                growth *= 1 + value
                peak = max(peak, growth)
                drawdown = min(drawdown, growth / peak - 1)
        rows.append(
            {
                "strategy": strategy,
                "folds": len(ordered),
                "observations": sum(len(fold.test_returns) for fold in ordered),
                "compounded_return": growth - 1,
                "worst_drawdown": drawdown,
            }
        )
    return pl.DataFrame(
        rows,
        schema={
            "strategy": pl.String,
            "folds": pl.Int64,
            "observations": pl.Int64,
            "compounded_return": pl.Float64,
            "worst_drawdown": pl.Float64,
        },
    )
