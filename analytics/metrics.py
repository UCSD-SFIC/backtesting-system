from __future__ import annotations

import math
from typing import Optional

import polars as pl


TRADING_DAYS_PER_YEAR = 252


def _to_daily_returns(growth: pl.Series) -> pl.Series:
    returns = growth.pct_change().drop_nulls()
    return returns.filter(returns.is_finite())


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


def calculate_annual_variance(growth: pl.Series) -> float:
    annualized_volatility = calculate_annualized_volatility(growth)
    return float(annualized_volatility**2)


def calculate_max_drawdown(growth: pl.Series) -> float:
    if growth.len() == 0:
        return 0.0

    wealth_index = growth.to_list()
    peak = wealth_index[0]
    max_dd = 0.0

    for value in wealth_index:
        peak = max(peak, value)
        if peak <= 0:
            continue
        drawdown = (value / peak) - 1
        max_dd = min(max_dd, drawdown)

    return float(max_dd)


def calculate_compounding_annual_return(growth: pl.Series) -> float:
    daily_returns = _to_daily_returns(growth)
    if daily_returns.len() == 0:
        return 0.0

    ending_growth = growth[-1]
    if ending_growth <= 0:
        return 0.0

    years = daily_returns.len() / TRADING_DAYS_PER_YEAR
    if years <= 0:
        return 0.0

    return float((ending_growth ** (1 / years)) - 1)


def calculate_win_rate(growth: pl.Series) -> float:
    daily_returns = _to_daily_returns(growth)
    total_periods = daily_returns.len()
    if total_periods == 0:
        return 0.0

    wins = daily_returns.filter(daily_returns > 0).len()
    return float(wins / total_periods)


def calculate_loss_rate(growth: pl.Series) -> float:
    daily_returns = _to_daily_returns(growth)
    total_periods = daily_returns.len()
    if total_periods == 0:
        return 0.0

    losses = daily_returns.filter(daily_returns < 0).len()
    return float(losses / total_periods)


def calculate_average_win(growth: pl.Series) -> float:
    daily_returns = _to_daily_returns(growth)
    wins = daily_returns.filter(daily_returns > 0)
    if wins.len() == 0:
        return 0.0

    mean = wins.mean()
    return float(mean) if mean is not None else 0.0


def calculate_average_loss(growth: pl.Series) -> float:
    daily_returns = _to_daily_returns(growth)
    losses = daily_returns.filter(daily_returns < 0)
    if losses.len() == 0:
        return 0.0

    mean = losses.mean()
    return float(mean) if mean is not None else 0.0


def calculate_profit_loss_ratio(growth: pl.Series) -> float:
    average_win = calculate_average_win(growth)
    average_loss = calculate_average_loss(growth)
    if average_loss == 0:
        return 0.0

    return float(abs(average_win / average_loss))


def calculate_expectancy(growth: pl.Series) -> float:
    win_rate = calculate_win_rate(growth)
    loss_rate = calculate_loss_rate(growth)
    average_win = calculate_average_win(growth)
    average_loss = calculate_average_loss(growth)
    return float((win_rate * average_win) + (loss_rate * average_loss))


def calculate_beta(growth: pl.Series, benchmark_returns: pl.Series) -> float:
    portfolio_returns = _to_daily_returns(growth)
    if portfolio_returns.len() == 0 or benchmark_returns.len() == 0:
        return 0.0

    aligned_length = min(portfolio_returns.len(), benchmark_returns.len())
    if aligned_length <= 1:
        return 0.0

    portfolio_returns = portfolio_returns.tail(aligned_length)
    benchmark_returns = benchmark_returns.tail(aligned_length)

    benchmark_variance = benchmark_returns.var()
    if benchmark_variance is None or benchmark_variance == 0:
        return 0.0

    portfolio_mean = portfolio_returns.mean()
    benchmark_mean = benchmark_returns.mean()
    if portfolio_mean is None or benchmark_mean is None:
        return 0.0

    covariance = (
        ((portfolio_returns - portfolio_mean) * (benchmark_returns - benchmark_mean)).sum()
        / (aligned_length - 1)
    )

    return float(covariance / benchmark_variance)


def calculate_alpha(
    growth: pl.Series,
    benchmark_returns: pl.Series,
    risk_free_rate: float = 0.02,
) -> float:
    beta = calculate_beta(growth, benchmark_returns)
    portfolio_return = calculate_compounding_annual_return(growth)

    aligned_length = benchmark_returns.len()
    if aligned_length == 0:
        return 0.0

    benchmark_growth = pl.Series(
        "benchmark_growth",
        [1.0] + [(1 + value) for value in benchmark_returns.to_list()],
    ).cum_prod()
    benchmark_return = calculate_compounding_annual_return(benchmark_growth)

    return float(portfolio_return - (risk_free_rate + beta * (benchmark_return - risk_free_rate)))


def _extract_benchmark_returns(
    backtest_df: pl.DataFrame,
    benchmark_ticker: Optional[str] = None,
) -> Optional[pl.Series]:
    candidate_column: Optional[str] = None
    if benchmark_ticker is not None:
        explicit_column = f"{benchmark_ticker}_return"
        if explicit_column in backtest_df.columns:
            candidate_column = explicit_column
    else:
        excluded_suffixes = (
            "_period_return",
            "_cumulative_return",
            "_weighted_return",
        )
        for column in backtest_df.columns:
            if not column.endswith("_return"):
                continue
            if column.startswith("overall_"):
                continue
            if column.endswith(excluded_suffixes):
                continue
            candidate_column = column
            break

    if candidate_column is None:
        return None

    return backtest_df[candidate_column].slice(1) - 1


def summarize_performance(
    backtest_df: pl.DataFrame,
    risk_free_rate: float = 0.02,
    benchmark_ticker: Optional[str] = None,
) -> dict[str, float]:
    growth = backtest_df["overall_growth"]
    total_return = float(backtest_df["overall_cumulative_return"].last())
    benchmark_returns = _extract_benchmark_returns(
        backtest_df,
        benchmark_ticker=benchmark_ticker,
    )

    summary = {
        "total_return": total_return,
        "compounding_annual_return": calculate_compounding_annual_return(growth),
        "sharpe_ratio": calculate_sharpe_ratio(growth, risk_free_rate),
        "sortino_ratio": calculate_sortino_ratio(growth, risk_free_rate),
        "annualized_volatility": calculate_annualized_volatility(growth),
        "annual_variance": calculate_annual_variance(growth),
        "max_drawdown": calculate_max_drawdown(growth),
        "win_rate": calculate_win_rate(growth),
        "loss_rate": calculate_loss_rate(growth),
        "average_win": calculate_average_win(growth),
        "average_loss": calculate_average_loss(growth),
        "profit_loss_ratio": calculate_profit_loss_ratio(growth),
        "expectancy": calculate_expectancy(growth),
        "beta": 0.0,
        "alpha": 0.0,
    }

    if benchmark_returns is not None:
        summary["beta"] = calculate_beta(growth, benchmark_returns)
        summary["alpha"] = calculate_alpha(
            growth,
            benchmark_returns,
            risk_free_rate=risk_free_rate,
        )

    return summary
