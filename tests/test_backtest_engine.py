from __future__ import annotations

import pytest

from engine.history import combine_ticker_histories
from pipeline.backtest import backtest


# Tests for the core portfolio calculation contract.


def test_backtest_applies_weights_by_rebalance_period(price_history, rebalance_weights):
    # Verifies weights apply from each rebalance date until the next one.
    combined_history = combine_ticker_histories(price_history)
    result = backtest(combined_history, rebalance_weights, ["A", "B"])

    expected_returns = [
        0.0,
        0.25,
        0.0,
        0.25,
    ]
    assert result["overall_cumulative_return"].to_list() == pytest.approx(
        expected_returns
    )


def test_backtest_result_includes_component_and_portfolio_columns(
    price_history, rebalance_weights
):
    # Verifies downstream metrics/plots get the expected result columns.
    combined_history = combine_ticker_histories(price_history)
    result = backtest(combined_history, rebalance_weights, ["A", "B"])

    expected_columns = {
        "timestamp",
        "A_close",
        "B_close",
        "A_cumulative_return",
        "B_cumulative_return",
        "overall_growth",
        "overall_cumulative_return",
    }
    assert expected_columns.issubset(set(result.columns))


def test_backtest_treats_unallocated_weight_as_cash():
    history = {
        "A": __import__("polars").DataFrame(
            {"timestamp": [1704171600000, 1704258000000], "close": [1.0, 2.0]}
        ),
        "B": __import__("polars").DataFrame(
            {"timestamp": [1704171600000, 1704258000000], "close": [1.0, 0.5]}
        ),
    }

    weights = __import__("polars").DataFrame(
        {
            "A": [0.0],
            "B": [0.0],
            "timestamp": __import__("polars").Series(["01/01/2024 5:00:00"]).str.strptime(
                __import__("polars").Datetime, "%d/%m/%Y %H:%M:%S"
            ),
        }
    )

    combined_history = combine_ticker_histories(history)
    result = backtest(combined_history, weights, ["A", "B"])

    assert result["overall_growth"].to_list() == pytest.approx([1.0, 1.0])
    assert result["overall_cumulative_return"].to_list() == pytest.approx([0.0, 0.0])
