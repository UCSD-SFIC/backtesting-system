from __future__ import annotations

import math

import polars as pl


TRADING_DAYS_PER_YEAR = 252


def _to_daily_returns(growth: pl.Series) -> pl.Series:
    return growth.pct_change().drop_nulls()


def calculate_sharpe_ratio(growth: pl.Series, risk_free_rate: float = 0.02) -> float:
    daily_returns = _to_daily_returns(growth)
    if daily_returns.len() == 0:
        return 0.0

    daily_rf = (1 + risk_free_rate) ** (1 / TRADING_DAYS_PER_YEAR) - 1
    excess_returns = daily_returns - daily_rf
    std = excess_returns.std()
    if std is None or std == 0:
        return 0.0

    return float((excess_returns.mean() / std) * math.sqrt(TRADING_DAYS_PER_YEAR))


def calculate_sortino_ratio(growth: pl.Series, risk_free_rate: float = 0.02) -> float:
    daily_returns = _to_daily_returns(growth)
    if daily_returns.len() == 0:
        return 0.0

    daily_rf = (1 + risk_free_rate) ** (1 / TRADING_DAYS_PER_YEAR) - 1
    excess_returns = daily_returns - daily_rf
    downside = excess_returns.filter(excess_returns < 0)
    if downside.len() == 0:
        return 0.0

    downside_std = downside.std()
    if downside_std is None or downside_std == 0:
        return 0.0

    return float((excess_returns.mean() / downside_std) * math.sqrt(TRADING_DAYS_PER_YEAR))


def calculate_annualized_volatility(growth: pl.Series) -> float:
    daily_returns = _to_daily_returns(growth)
    if daily_returns.len() == 0:
        return 0.0

    std = daily_returns.std()
    if std is None:
        return 0.0

    return float(std * math.sqrt(TRADING_DAYS_PER_YEAR))


def calculate_max_drawdown(growth: pl.Series) -> float:
    if growth.len() == 0:
        return 0.0

    wealth_index = growth.to_list()
    peak = wealth_index[0]
    max_dd = 0.0

    for value in wealth_index:
        peak = max(peak, value)
        drawdown = (value / peak) - 1
        max_dd = min(max_dd, drawdown)

    return float(max_dd)


def summarize_performance(
    backtest_df: pl.DataFrame,
    risk_free_rate: float = 0.02,
) -> dict[str, float]:
    growth = backtest_df["overall_growth"]
    total_return = float(backtest_df["overall_cumulative_return"].last())

    return {
        "total_return": total_return,
        "sharpe_ratio": calculate_sharpe_ratio(growth, risk_free_rate),
        "sortino_ratio": calculate_sortino_ratio(growth, risk_free_rate),
        "annualized_volatility": calculate_annualized_volatility(growth),
        "max_drawdown": calculate_max_drawdown(growth),
    }
