"""Deterministic portfolio research and stress calculations.

Scenario shocks are explicit assumptions, not forecasts. Historical comparison
uses only dates where every selected asset and benchmark has a return.
"""

from __future__ import annotations

import math

import numpy as np
import polars as pl


def _validate_portfolios(portfolios: dict[str, dict[str, float]]) -> None:
    if not portfolios:
        raise ValueError("at least one portfolio is required")
    for name, weights in portfolios.items():
        if not weights or any(not math.isfinite(w) or w < 0 for w in weights.values()):
            raise ValueError(f"{name}: weights must be finite and nonnegative")
        total = sum(weights.values())
        if not 0 < total <= 1 + 1e-9:
            raise ValueError(f"{name}: weights must sum to more than 0 and at most 1")


def historical_returns(prices: pl.DataFrame) -> pl.DataFrame:
    """Convert long dated close prices into a date-aligned wide return matrix."""
    required = {"timestamp", "ticker", "close"}
    if not required.issubset(prices.columns):
        raise ValueError(f"prices missing columns: {sorted(required - set(prices.columns))}")
    if prices.is_empty():
        raise ValueError("prices cannot be empty")
    if prices.select(pl.struct("timestamp", "ticker").is_duplicated().any()).item():
        raise ValueError("duplicate timestamp/ticker price")
    if (
        prices.select(pl.col("close").is_null().any()).item()
        or prices.select((pl.col("close") <= 0).any()).item()
    ):
        raise ValueError("close prices must be positive and nonnull")
    aligned = prices.pivot(on="ticker", index="timestamp", values="close").sort("timestamp")
    return aligned.select(
        "timestamp",
        *[
            pl.when(pl.col(ticker).is_not_null() & pl.col(ticker).shift(1).is_not_null())
            .then(pl.col(ticker) / pl.col(ticker).shift(1) - 1)
            .otherwise(None)
            .alias(ticker)
            for ticker in aligned.columns
            if ticker != "timestamp"
        ],
    )


def compare_portfolios(
    returns: pl.DataFrame,
    portfolios: dict[str, dict[str, float]],
    benchmark: str,
) -> pl.DataFrame:
    """Compare dated simple returns for candidate portfolios against a benchmark."""
    _validate_portfolios(portfolios)
    assets = set().union(*(set(weights) for weights in portfolios.values())) | {benchmark}
    missing = assets - set(returns.columns)
    if missing:
        raise ValueError(f"returns missing assets: {sorted(missing)}")
    rows = []
    for name, weights in portfolios.items():
        aligned = returns.select(benchmark, *[t for t in weights if t != benchmark]).drop_nulls()
        if aligned.is_empty():
            raise ValueError(f"{name}: no aligned return observations")
        portfolio = np.array(
            [
                sum(weights[ticker] * row[ticker] for ticker in weights)
                for row in aligned.to_dicts()
            ],
            dtype=float,
        )
        market = np.asarray(aligned[benchmark].to_list(), dtype=float)
        if not np.isfinite(portfolio).all() or not np.isfinite(market).all():
            raise ValueError(f"{name}: returns must be finite")
        growth = np.cumprod(1 + portfolio)
        peak = np.maximum.accumulate(np.r_[1.0, growth])[1:]
        correlation = (
            float(np.corrcoef(portfolio, market)[0, 1])
            if len(portfolio) > 1 and np.std(portfolio) > 0 and np.std(market) > 0
            else None
        )
        rows.append(
            {
                "portfolio": name,
                "observations": len(portfolio),
                "cumulative_return": float(growth[-1] - 1),
                "max_drawdown": float(np.min(growth / peak - 1)),
                "annualized_volatility": float(np.std(portfolio, ddof=1) * np.sqrt(252))
                if len(portfolio) > 1
                else 0.0,
                "correlation_to_benchmark": correlation,
                "concentration": float(sum(w * w for w in weights.values())),
            }
        )
    return pl.DataFrame(rows)


def scenario_sensitivity(
    portfolios: dict[str, dict[str, float]],
    shocks: dict[str, dict[str, float]],
) -> pl.DataFrame:
    """Apply assumed one-period asset shocks and report contribution by asset."""
    _validate_portfolios(portfolios)
    if not shocks:
        raise ValueError("at least one scenario is required")
    rows = []
    for scenario, assumed_returns in shocks.items():
        for portfolio, weights in portfolios.items():
            missing = set(weights) - set(assumed_returns)
            if missing:
                raise ValueError(f"{scenario}: missing shocks for {sorted(missing)}")
            for ticker in weights:
                shock = assumed_returns[ticker]
                if not math.isfinite(shock) or shock < -1:
                    raise ValueError(f"{scenario}: shock for {ticker} must be finite and >= -1")
            total = sum(weights[t] * assumed_returns[t] for t in weights)
            rows.extend(
                {
                    "scenario": scenario,
                    "portfolio": portfolio,
                    "ticker": ticker,
                    "weight": weight,
                    "asset_shock": assumed_returns[ticker],
                    "contribution": weight * assumed_returns[ticker],
                    "portfolio_shock": total,
                }
                for ticker, weight in weights.items()
            )
    return pl.DataFrame(rows)


__all__ = ["historical_returns", "compare_portfolios", "scenario_sensitivity"]
