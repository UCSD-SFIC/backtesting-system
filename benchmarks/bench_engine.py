"""
Engine benchmark on synthetic data.

Run with `python -m benchmarks.bench_engine [--tickers 100] [--days 1260] [--output f.json]`.
The defaults are 100 tickers over five years of daily bars. Data is seeded,
so timings are comparable between runs on the same machine.
"""

from __future__ import annotations

import argparse
import json
import time
from collections.abc import Callable
from typing import TypeVar

import numpy as np
import polars as pl

from engine.backtest_engine import BacktestEngine
from engine.history import combine_ticker_histories
from engine.weights import build_weight_frame
from strategy.alpha import Alpha

T = TypeVar("T")

DAY_MS = 24 * 60 * 60 * 1000
START_MS = 1420070400000  # 2015-01-01 UTC


class RotatingEqualWeightAlpha(Alpha):
    """Holds a rotating half of the universe at equal weight; cheap but non-trivial."""

    def __init__(self, tickers: list[str]):
        self._tickers = tickers
        self._step = 0
        self._weights = [0.0] * len(tickers)

    def get_tickers(self) -> list[str]:
        return self._tickers

    def get_weights(self) -> list[float]:
        return self._weights

    def update(self, market_slice: pl.DataFrame) -> None:
        self._step += 1
        n = len(self._tickers)
        held = {(self._step // 21 + i) % n for i in range(n // 2)}
        self._weights = [1.0 / len(held) if i in held else 0.0 for i in range(n)]


def synthetic_history(n_tickers: int, n_days: int, seed: int = 7) -> dict[str, pl.DataFrame]:
    rng = np.random.default_rng(seed)
    timestamps = START_MS + np.arange(n_days, dtype=np.int64) * DAY_MS
    histories: dict[str, pl.DataFrame] = {}
    for i in range(n_tickers):
        returns = rng.normal(0.0004, 0.015, n_days)
        close = 100.0 * np.cumprod(1 + returns)
        histories[f"T{i:03d}"] = pl.DataFrame(
            {
                "timestamp": timestamps,
                "open": close,
                "high": close * 1.01,
                "low": close * 0.99,
                "close": close,
                "volume": np.full(n_days, 1e6),
            }
        )
    return histories


def best_of(fn: Callable[[], T], repeat: int) -> tuple[float, T]:
    best = float("inf")
    result = None
    for _ in range(repeat):
        start = time.perf_counter()
        result = fn()
        best = min(best, time.perf_counter() - start)
    assert result is not None
    return best, result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", type=int, default=100)
    parser.add_argument("--days", type=int, default=1260)
    parser.add_argument("--repeat", type=int, default=3)
    parser.add_argument("--output", help="also write the result JSON to this file")
    args = parser.parse_args()

    raw = synthetic_history(args.tickers, args.days)
    tickers = list(raw)

    combine_s, history = best_of(lambda: combine_ticker_histories(raw), args.repeat)
    weights_s, weights = best_of(
        lambda: build_weight_frame(RotatingEqualWeightAlpha(tickers), history), args.repeat
    )
    engine = BacktestEngine(data_provider=None)
    backtest_s, result = best_of(
        lambda: engine.run_portfolio_backtest(history, weights, tickers), args.repeat
    )

    report = json.dumps(
        {
            "tickers": args.tickers,
            "days": args.days,
            "combine_ticker_histories_s": round(combine_s, 4),
            "build_weight_frame_s": round(weights_s, 4),
            "run_portfolio_backtest_s": round(backtest_s, 4),
            "total_s": round(combine_s + weights_s + backtest_s, 4),
            "final_return": round(float(result["overall_cumulative_return"][-1]), 6),
        },
        indent=2,
    )
    print(report)
    if args.output:
        with open(args.output, "w") as file:
            file.write(report + "\n")


if __name__ == "__main__":
    main()
