from __future__ import annotations

import pytest
import polars as pl

from analytics.metrics import (
    calculate_alpha,
    calculate_average_loss,
    calculate_average_win,
    calculate_annualized_volatility,
    calculate_annual_variance,
    calculate_beta,
    calculate_compounding_annual_return,
    calculate_expectancy,
    calculate_loss_rate,
    calculate_max_drawdown,
    calculate_profit_loss_ratio,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_win_rate,
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


def test_summarize_performance_includes_all_readme_metrics():
    # Verifies the published README metric list matches the computed summary keys.
    backtest_df = pl.DataFrame(
        {
            "overall_growth": [1.0, 1.1, 1.0, 1.2],
            "overall_cumulative_return": [0.0, 0.1, 0.0, 0.2],
        }
    )

    summary = summarize_performance(backtest_df, risk_free_rate=0.0)

    assert {
        "total_return",
        "compounding_annual_return",
        "sharpe_ratio",
        "sortino_ratio",
        "annualized_volatility",
        "annual_variance",
        "max_drawdown",
        "win_rate",
        "loss_rate",
        "average_win",
        "average_loss",
        "profit_loss_ratio",
        "expectancy",
        "beta",
        "alpha",
    }.issubset(set(summary.keys()))


def test_distribution_and_benchmark_metrics_match_expected_values():
    backtest_df = pl.DataFrame(
        {
            "overall_growth": [1.0, 1.1, 1.045, 1.254, 1.1286],
            "overall_cumulative_return": [0.0, 0.1, 0.045, 0.254, 0.1286],
            "SPY_return": [1.0, 1.05, 0.975, 1.10, 0.95],
        }
    )

    growth = backtest_df["overall_growth"]
    benchmark_returns = pl.Series([0.05, -0.025, 0.10, -0.05])

    assert calculate_win_rate(growth) == pytest.approx(0.5)
    assert calculate_loss_rate(growth) == pytest.approx(0.5)
    assert calculate_average_win(growth) == pytest.approx(0.15)
    assert calculate_average_loss(growth) == pytest.approx(-0.075)
    assert calculate_profit_loss_ratio(growth) == pytest.approx(2.0)
    assert calculate_expectancy(growth) == pytest.approx(0.0375)
    assert calculate_beta(growth, benchmark_returns) == pytest.approx(2.0)
    assert calculate_alpha(growth, benchmark_returns, risk_free_rate=0.0) == pytest.approx(
        calculate_compounding_annual_return(growth)
        - (calculate_beta(growth, benchmark_returns) * calculate_compounding_annual_return(pl.Series([1.0, 1.05, 1.02375, 1.126125, 1.06981875])))
    )
    assert calculate_compounding_annual_return(growth) == pytest.approx(
        (growth[-1] ** (252 / 4)) - 1
    )
    assert calculate_annual_variance(growth) == pytest.approx(
        calculate_annualized_volatility(growth) ** 2
    )

    summary = summarize_performance(backtest_df, risk_free_rate=0.0, benchmark_ticker="SPY")

    assert summary["win_rate"] == pytest.approx(0.5)
    assert summary["loss_rate"] == pytest.approx(0.5)
    assert summary["average_win"] == pytest.approx(0.15)
    assert summary["average_loss"] == pytest.approx(-0.075)
    assert summary["profit_loss_ratio"] == pytest.approx(2.0)
    assert summary["expectancy"] == pytest.approx(0.0375)
    assert summary["beta"] == pytest.approx(2.0)
    assert "alpha" in summary
    assert summary["compounding_annual_return"] == pytest.approx(
        (growth[-1] ** (252 / 4)) - 1
    )


def test_metrics_handle_zero_growth_paths_without_crashing():
    backtest_df = pl.DataFrame(
        {
            "overall_growth": [0.0, 0.0, 0.0, 1.05],
            "overall_cumulative_return": [-1.0, -1.0, -1.0, 0.05],
            "SPY_return": [1.0, 1.0, 1.0, 1.02],
        }
    )

    summary = summarize_performance(backtest_df, risk_free_rate=0.0, benchmark_ticker="SPY")

    assert summary["max_drawdown"] <= 0.0
    assert summary["annualized_volatility"] >= 0.0
