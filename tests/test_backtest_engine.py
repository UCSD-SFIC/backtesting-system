from __future__ import annotations

import pytest

from backtest import backtest
from engine_layer.history import combine_ticker_histories


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
