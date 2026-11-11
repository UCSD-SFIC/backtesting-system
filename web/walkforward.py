"""Run an out of sample study from a saved allocation backtest."""

from __future__ import annotations

import datetime as dt

import polars as pl

from experiments.store import RunRecord, load_frame
from research.evaluation import evaluate_allocation_walk_forward


def evaluate_saved_run(record: RunRecord, train_size: int, test_size: int) -> dict:
    config = record.config
    strategy = config.get("strategy", {})
    if strategy.get("name") != "allocation":
        raise ValueError("Walk forward evaluation requires an allocation run")
    history = load_frame(record, "price_history")
    if "timestamp" not in history.columns:
        raise ValueError("Saved history has no timestamp")
    timestamp = (
        pl.col("timestamp").dt.epoch("ms")
        if history.schema["timestamp"].is_temporal()
        else pl.col("timestamp").cast(pl.Int64)
    )
    histories = {
        column.removesuffix("_close"): history.select(
            timestamp.alias("timestamp"), pl.col(column).alias("close")
        ).drop_nulls()
        for column in history.columns
        if column.endswith("_close")
    }
    params = dict(strategy.get("params", {}))
    params.pop("benchmark", None)
    counts = params.get("sleeve_top_n", {})
    candidates = {
        "saved_mix": params,
        "momentum_only": {
            **params, "sleeves": {"momentum": 1.0},
            "sleeve_top_n": {"momentum": counts["momentum"]} if "momentum" in counts else None,
        },
        "high_52_week_only": {
            **params, "sleeves": {"high_52_week": 1.0},
            "sleeve_top_n": (
                {"high_52_week": counts["high_52_week"]}
                if "high_52_week" in counts else None
            ),
        },
    }
    result = evaluate_allocation_walk_forward(
        histories, candidates,
        start=dt.date.fromisoformat(config["start"]),
        end=dt.date.fromisoformat(config["end"]),
        train_size=train_size, test_size=test_size,
        investable=config["tickers"], benchmark=config.get("benchmark"),
        cost_bps=config.get("execution", {}).get("cost_bps", 0.0),
    )
    return {
        "summary": result.summary,
        "folds": [
            {"selected": fold.selected, "train_return": fold.train_return,
             "test_return": fold.test_return, "train_end": fold.window.train_end,
             "test_begin": fold.window.test_begin}
            for fold in result.folds
        ],
        "candidates": result.candidate_summary.to_dicts(),
    }
