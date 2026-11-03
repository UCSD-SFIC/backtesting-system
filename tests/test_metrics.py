from __future__ import annotations

import datetime as dt
import math

import polars as pl
import pytest

from analytics.metrics import (
    calculate_alpha,
    calculate_annual_variance,
    calculate_annualized_volatility,
    calculate_average_loss,
    calculate_average_win,
    calculate_beta,
    calculate_compounding_annual_return,
    calculate_expectancy,
    calculate_loss_rate,
    calculate_max_drawdown,
    calculate_profit_loss_ratio,
    calculate_sharpe_ratio,
    calculate_sortino_ratio,
    calculate_win_rate,
    infer_periods_per_year,
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
    benchmark_growth = pl.Series([1.0, 1.05, 1.02375, 1.126125, 1.06981875])
    assert calculate_alpha(growth, benchmark_returns, risk_free_rate=0.0) == pytest.approx(
        calculate_compounding_annual_return(growth)
        - calculate_beta(growth, benchmark_returns)
        * calculate_compounding_annual_return(benchmark_growth)
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


def _bars(start: dt.datetime, step: dt.timedelta, count: int) -> pl.Series:
    return pl.Series([start + i * step for i in range(count)])


def _session_bars(hours: list[int], days: int) -> pl.Series:
    # Bars at the given UTC hours on consecutive weekdays.
    start = dt.date(2025, 1, 6)
    stamps = []
    day = start
    while len(stamps) < days * len(hours):
        if day.weekday() < 5:
            stamps += [dt.datetime(day.year, day.month, day.day, hour) for hour in hours]
        day += dt.timedelta(days=1)
    return pl.Series(stamps)


def test_infer_periods_per_year_by_bar_frequency():
    start = dt.datetime(2024, 1, 1)

    assert infer_periods_per_year(_bars(start, dt.timedelta(days=1), 30)) == 252
    assert infer_periods_per_year(_bars(start, dt.timedelta(weeks=1), 30)) == 52
    assert infer_periods_per_year(_bars(start, dt.timedelta(days=30), 30)) == 12
    # yfinance hourly: 7 bars per session; 2-hour resample: 4 bars per session.
    assert infer_periods_per_year(_session_bars(list(range(14, 21)), 20)) == 252 * 7
    assert infer_periods_per_year(_session_bars([12, 14, 16, 18], 20)) == 252 * 4


def test_infer_periods_per_year_handles_epoch_ms_and_short_input():
    daily_ms = pl.Series([1704171600000 + i * 86_400_000 for i in range(10)])

    assert infer_periods_per_year(daily_ms) == 252
    assert infer_periods_per_year(pl.Series([dt.datetime(2024, 1, 1)])) == 252


def test_annualized_metrics_scale_with_periods_per_year():
    growth = pl.Series([1.0, 1.01, 0.995, 1.02, 1.03])

    daily_vol = calculate_annualized_volatility(growth)
    hourly_vol = calculate_annualized_volatility(growth, periods_per_year=252 * 7)

    assert hourly_vol == pytest.approx(daily_vol * math.sqrt(7))
    assert calculate_compounding_annual_return(growth, 4) == pytest.approx(0.03)
    assert calculate_annual_variance(growth, 52) == pytest.approx(
        calculate_annualized_volatility(growth, 52) ** 2
    )


def test_intraday_summary_annualizes_by_trading_time():
    # Regression: 2-hour runs were annualized as if each bar were a day, so a
    # +8% return over most of a year reported a ~2% compounding annual return.
    timestamps = _session_bars([12, 14, 16, 18], 220)
    bars = timestamps.len()
    growth = pl.Series([1.08 ** (i / (bars - 1)) for i in range(bars)])
    backtest_df = pl.DataFrame(
        {
            "timestamp": timestamps,
            "overall_growth": growth,
            "overall_cumulative_return": growth - 1,
        }
    )

    summary = summarize_performance(backtest_df, risk_free_rate=0.0)

    assert summary["periods_per_year"] == 252 * 4
    years = (bars - 1) / (252 * 4)
    assert summary["compounding_annual_return"] == pytest.approx(1.08 ** (1 / years) - 1)
    assert summary["compounding_annual_return"] > summary["total_return"]


def test_explicit_periods_per_year_overrides_inference():
    backtest_df = pl.DataFrame(
        {
            "timestamp": _bars(dt.datetime(2024, 1, 1), dt.timedelta(days=1), 5),
            "overall_growth": [1.0, 1.1, 1.0, 1.2, 1.25],
            "overall_cumulative_return": [0.0, 0.1, 0.0, 0.2, 0.25],
        }
    )

    summary = summarize_performance(backtest_df, risk_free_rate=0.0, periods_per_year=4)

    assert summary["periods_per_year"] == 4
    assert summary["compounding_annual_return"] == pytest.approx(0.25)
