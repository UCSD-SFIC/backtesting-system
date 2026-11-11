"""Walk-forward selection uses training observations only."""

from __future__ import annotations

import datetime as dt

import polars as pl
import pytest

from research.evaluation import (
    evaluate_allocation_walk_forward,
    evaluate_candidate_returns,
    run_allocation_candidates,
)


def test_test_period_shock_does_not_change_earlier_selection():
    dates = [dt.date(2024, 1, day) for day in range(1, 9)]
    returns = pl.DataFrame(
        {
            "date": dates,
            "A": [0.05, 0.05, 0.05, -0.9, -0.9, 0.0, 0.0, 0.0],
            "B": [0.0, 0.0, 0.0, 0.9, 0.9, 0.0, 0.0, 0.0],
        }
    )
    first = evaluate_candidate_returns(returns, train_size=3, test_size=2)
    shocked = returns.with_columns(
        pl.when(pl.int_range(pl.len()) >= 3).then(pl.lit(-0.95)).otherwise(pl.col("B")).alias("B")
    )
    second = evaluate_candidate_returns(shocked, train_size=3, test_size=2)

    assert first.folds[0].selected == second.folds[0].selected == "A"
    assert first.folds[0].test_return == pytest.approx(0.01 - 1)
    assert first.folds[0].window.train_end < first.folds[0].window.test_begin


def test_selection_uses_each_fold_training_interval_and_tie_is_deterministic():
    dates = [dt.date(2024, 1, day) for day in range(1, 8)]
    returns = pl.DataFrame(
        {
            "date": dates,
            "B": [0.0, 0.0, 0.0, 0.5, 0.5, 0.1, 0.1],
            "A": [0.1, 0.1, 0.1, -0.1, -0.1, 0.0, 0.0],
        }
    )
    evaluation = evaluate_candidate_returns(returns, train_size=3, test_size=2)
    assert [fold.selected for fold in evaluation.folds] == ["A", "B"]
    assert evaluation.summary["folds"] == 2
    assert evaluation.summary["observations"] == 4


@pytest.mark.parametrize(
    "frame",
    [
        pl.DataFrame({"date": [dt.date(2024, 1, 1)], "A": [float("nan")]}),
        pl.DataFrame({"date": [dt.date(2024, 1, 1)], "A": [-1.1]}),
        pl.DataFrame({"date": [dt.date(2024, 1, 1)], "A": [None]}),
    ],
)
def test_rejects_invalid_candidate_returns(frame):
    with pytest.raises(ValueError, match="returns"):
        evaluate_candidate_returns(frame, train_size=1, test_size=1)


def test_runs_allocation_candidates_on_offline_history():
    dates = [dt.date(2024, 1, 1) + dt.timedelta(days=i) for i in range(25)]
    timestamps = [
        int(dt.datetime.combine(day, dt.time(), dt.timezone.utc).timestamp() * 1000)
        for day in dates
    ]
    histories = {
        "A": pl.DataFrame({"timestamp": timestamps, "close": [10.0 + i for i in range(25)]}),
        "B": pl.DataFrame({"timestamp": timestamps, "close": [20.0 + i / 10 for i in range(25)]}),
    }
    candidates = {
        "short": {
            "sleeves": {"momentum": 1.0},
            "lookback": 3,
            "skip": 0,
            "high_window": 3,
            "top_n": 1,
            "min_price": 0.0,
        },
        "long": {
            "sleeves": {"momentum": 1.0},
            "lookback": 5,
            "skip": 0,
            "high_window": 3,
            "top_n": 1,
            "min_price": 0.0,
        },
    }
    table = run_allocation_candidates(histories, candidates, start=dates[5], end=dates[-1])
    assert {"date", "short", "long"} <= set(table.columns)
    assert table.height >= 10
    assert table["date"][0] >= dates[5]
    assert table["date"][-1] <= dates[-1]
    result = evaluate_allocation_walk_forward(
        histories, candidates, start=dates[5], end=dates[-1], train_size=5, test_size=3
    )
    assert len(result.folds) >= 1
