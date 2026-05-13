from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from strategy.wednesday_plus_alpha import WednesdayPlusAlpha


def _slice(timestamp: str, prices: dict[str, float]) -> pl.DataFrame:
    data = {f"{symbol}_close": [price] for symbol, price in prices.items()}
    return pl.DataFrame(data).with_columns(
        pl.lit(timestamp).str.strptime(pl.Datetime, "%Y-%m-%d").alias("timestamp")
    )


def _alpha() -> WednesdayPlusAlpha:
    return WednesdayPlusAlpha(
        "US",
        "day",
        WednesdayPlusAlpha.default_tickers(),
        "2024-01-01",
        "2024-12-31",
    )


def test_wednesday_plus_exposes_full_universe():
    assert WednesdayPlusAlpha.default_tickers() == [
        "SPY",
        "SPLV",
        "QUAL",
        "APP",
        "NVDA",
        "AAPL",
        "MSFT",
        "GOOGL",
        "AMZN",
        "META",
    ]


def test_wednesday_plus_uses_neutral_core_before_ff_is_ready():
    alpha = _alpha()
    prices = {symbol: 100.0 for symbol in alpha.get_tickers()}

    alpha.update(_slice("2024-01-01", prices))
    weights = dict(zip(alpha.get_tickers(), alpha.get_weights()))

    assert weights["SPY"] > weights["SPLV"]
    assert weights["SPLV"] > 0
    assert abs(sum(weights.values()) - 1.0) < 1e-12


def test_wednesday_plus_selects_top_momentum_names_for_sleeve():
    alpha = _alpha()
    tickers = alpha.get_tickers()

    start = date(2024, 1, 1)
    for day in range(1, 96):
        prices = {
            "SPY": 100.0 + day,
            "SPLV": 100.0 + day * 0.5,
            "QUAL": 100.0 + day * 0.4,
            "APP": 100.0 + day * 0.3,
            "NVDA": 100.0 + day * 0.2,
            "AAPL": 100.0 + day * 4.0,
            "MSFT": 100.0 + day * 3.0,
            "GOOGL": 100.0 + day * 2.0,
            "AMZN": 100.0 + day * 1.0,
            "META": 100.0 + day * 0.5,
        }
        timestamp = (start + timedelta(days=day)).isoformat()
        alpha.update(_slice(timestamp, {symbol: prices[symbol] for symbol in tickers}))

    alpha._rebalance_momentum(alpha.SLEEVE_RISK_ON)

    assert alpha.selected_momentum == ["AAPL", "MSFT", "GOOGL"]
