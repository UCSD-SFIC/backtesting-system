from __future__ import annotations

import pytest
import polars as pl

from analytics.metrics import (
    calculate_annualized_volatility,
    calculate_max_drawdown,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    summarize_performance,
)


# Tests for performance metric edge cases and summary output.


def test_metrics_return_zero_when_no_returns_exist():
    # Verifies one-point growth series do not produce noisy metric values.
    growth = pl.Series([1.0])

    assert calculate_sharpe_ratio(growth) == 0.0
    assert calculate_sortino_ratio(growth) == 0.0
    assert calculate_annualized_volatility(growth) == 0.0
    assert calculate_max_drawdown(growth) == 0.0


def test_max_drawdown_uses_running_peak():
    # Verifies drawdown is measured from the previous high-water mark.
    growth = pl.Series([1.0, 1.1, 1.0, 1.2])

    assert calculate_max_drawdown(growth) == pytest.approx((1.0 / 1.1) - 1)


def test_summarize_performance_reports_total_return_and_risk_metrics():
    # Verifies summary exposes total return plus the core risk metrics.
    backtest_df = pl.DataFrame(
        {
            "overall_growth": [1.0, 1.1, 1.0, 1.2],
            "overall_cumulative_return": [0.0, 0.1, 0.0, 0.2],
        }
    )

    summary = summarize_performance(backtest_df, risk_free_rate=0.0)

    assert summary["total_return"] == pytest.approx(0.2)
    assert summary["max_drawdown"] == pytest.approx((1.0 / 1.1) - 1)
    assert summary["annualized_volatility"] > 0
    assert summary["sharpe_ratio"] != 0
