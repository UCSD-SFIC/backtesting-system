"""Deterministic whole-share paper rebalancing without order execution."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Trade:
    ticker: str
    current_shares: int
    target_shares: int
    delta_shares: int
    price: float
    estimated_cost: float


@dataclass(frozen=True)
class RebalanceResult:
    trades: tuple[Trade, ...]
    starting_value: float
    ending_cash: float
    turnover: float
    estimated_cost: float


def _finite_nonnegative(value: float, label: str) -> None:
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{label} must be finite and nonnegative")


def rebalance(
    target_weights: Mapping[str, float],
    prices: Mapping[str, float],
    holdings: Mapping[str, int],
    cash: float,
    cost_bps: float = 0.0,
) -> RebalanceResult:
    """Calculate an affordable paper rebalance, selling before buying.

    Each desired position is rounded down to whole shares. If buying power is
    insufficient after simulated costs, buys are filled in ticker order until
    cash is exhausted. Returned target shares are the affordable positions.
    """
    _finite_nonnegative(cash, "cash")
    _finite_nonnegative(cost_bps, "cost_bps")
    if cost_bps > 10_000:
        raise ValueError("cost_bps cannot exceed 10000")
    for ticker, weight in target_weights.items():
        if not ticker or not ticker.strip():
            raise ValueError("ticker cannot be blank")
        _finite_nonnegative(weight, f"weight for {ticker}")
    if sum(target_weights.values()) > 1 + 1e-9:
        raise ValueError("target weights cannot exceed 1")
    for ticker, shares in holdings.items():
        if not isinstance(shares, int) or isinstance(shares, bool) or shares < 0:
            raise ValueError(f"shares for {ticker} must be a nonnegative integer")
    tickers = sorted(set(target_weights) | set(holdings))
    for ticker in tickers:
        price = prices.get(ticker)
        if price is None or not math.isfinite(price) or price <= 0:
            raise ValueError(f"price for {ticker} must be finite and positive")

    starting_value = cash + sum(holdings.get(t, 0) * prices[t] for t in tickers)
    cost_rate = cost_bps / 10_000
    desired = {
        ticker: math.floor(starting_value * target_weights.get(ticker, 0) / prices[ticker])
        for ticker in tickers
    }
    actual = dict(holdings)
    remaining_cash = cash

    # Sales supply cash for the purchases, net of estimated selling costs.
    for ticker in tickers:
        shares_sold = max(actual.get(ticker, 0) - desired[ticker], 0)
        actual[ticker] = actual.get(ticker, 0) - shares_sold
        remaining_cash += shares_sold * prices[ticker] * (1 - cost_rate)

    for ticker in tickers:
        desired_buy = max(desired[ticker] - actual.get(ticker, 0), 0)
        affordable = max(
            math.floor((remaining_cash + 1e-10) / (prices[ticker] * (1 + cost_rate))), 0
        )
        shares_bought = min(desired_buy, affordable)
        actual[ticker] = actual.get(ticker, 0) + shares_bought
        remaining_cash -= shares_bought * prices[ticker] * (1 + cost_rate)

    trades = tuple(
        Trade(
            ticker=ticker,
            current_shares=holdings.get(ticker, 0),
            target_shares=actual.get(ticker, 0),
            delta_shares=actual.get(ticker, 0) - holdings.get(ticker, 0),
            price=prices[ticker],
            estimated_cost=abs(actual.get(ticker, 0) - holdings.get(ticker, 0))
            * prices[ticker]
            * cost_rate,
        )
        for ticker in tickers
    )
    gross_traded = sum(abs(t.delta_shares) * t.price for t in trades)
    return RebalanceResult(
        trades=trades,
        starting_value=starting_value,
        ending_cash=max(remaining_cash, 0.0),
        turnover=gross_traded / starting_value if starting_value else 0.0,
        estimated_cost=sum(t.estimated_cost for t in trades),
    )
