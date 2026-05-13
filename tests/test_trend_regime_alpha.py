from __future__ import annotations

import polars as pl

from strategy.trend_regime_alpha import TrendRegimeAlpha


def _slice(timestamp: str, spy_close: float, sh_close: float) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "SPY_close": [spy_close],
            "SH_close": [sh_close],
        }
    ).with_columns(pl.lit(timestamp).str.strptime(pl.Datetime, "%Y-%m-%d").alias("timestamp"))


def _alpha() -> TrendRegimeAlpha:
    return TrendRegimeAlpha(
        "US",
        "day",
        ["SPY", "SH"],
        "2024-01-01",
        "2024-12-31",
        trend_window=3,
        short_momentum_window=1,
        medium_momentum_window=2,
        exit_threshold=-0.01,
    )


def test_dual_momentum_starts_long_primary_during_warmup():
    alpha = _alpha()

    alpha.update(_slice("2024-01-01", 100.0, 100.0))

    assert alpha.get_weights() == [1.0, 0.0]


def test_dual_momentum_stays_long_primary_in_positive_trend():
    alpha = _alpha()

    for day, spy_price in enumerate([100.0, 101.0, 103.0, 105.0], start=1):
        alpha.update(_slice(f"2024-01-0{day}", spy_price, 100.0))

    assert alpha.get_weights() == [1.0, 0.0]


def test_dual_momentum_stays_long_primary_when_hedge_is_not_leading():
    alpha = _alpha()

    prices = [
        ("2024-01-01", 100.0, 100.0),
        ("2024-01-02", 99.0, 99.0),
        ("2024-01-03", 98.0, 98.0),
        ("2024-01-04", 97.0, 97.0),
    ]
    for timestamp, spy_price, sh_price in prices:
        alpha.update(_slice(timestamp, spy_price, sh_price))

    assert alpha.get_weights() == [1.0, 0.0]


def test_dual_momentum_rotates_to_hedge_when_primary_is_below_trend_and_falling():
    alpha = _alpha()

    prices = [
        ("2024-01-01", 100.0, 100.0),
        ("2024-01-02", 99.0, 101.0),
        ("2024-01-03", 98.0, 102.0),
        ("2024-01-04", 97.0, 103.0),
    ]
    for timestamp, spy_price, sh_price in prices:
        alpha.update(_slice(timestamp, spy_price, sh_price))

    assert alpha.get_weights() == [0.0, 1.0]


def test_dual_momentum_stays_long_if_pullback_is_not_strong_enough():
    alpha = _alpha()

    prices = [
        ("2024-01-01", 100.0, 100.0),
        ("2024-01-02", 101.0, 99.5),
        ("2024-01-03", 100.5, 99.7),
        ("2024-01-04", 100.0, 100.0),
    ]
    for timestamp, spy_price, sh_price in prices:
        alpha.update(_slice(timestamp, spy_price, sh_price))

    assert alpha.get_weights() == [1.0, 0.0]
