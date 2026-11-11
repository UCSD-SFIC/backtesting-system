import datetime as dt

import polars as pl
import pytest

from research import compare_portfolios, historical_returns, scenario_sensitivity


def test_historical_returns_align_by_date_and_ticker():
    prices = pl.DataFrame(
        {
            "timestamp": [
                dt.date(2024, 1, 1),
                dt.date(2024, 1, 2),
                dt.date(2024, 1, 1),
                dt.date(2024, 1, 3),
            ],
            "ticker": ["SPY", "SPY", "SH", "SH"],
            "close": [100.0, 110.0, 100.0, 90.0],
        }
    )
    result = historical_returns(prices)
    assert result["timestamp"].to_list() == [
        dt.date(2024, 1, 1),
        dt.date(2024, 1, 2),
        dt.date(2024, 1, 3),
    ]
    assert result["SPY"].to_list() == [None, pytest.approx(0.1), None]
    # A two-day move is not mislabeled as a one-day return after a missing bar.
    assert result["SH"].to_list() == [None, None, None]


def test_compare_portfolios_uses_only_aligned_observations():
    returns = pl.DataFrame(
        {
            "timestamp": [1, 2, 3, 4],
            "SPY": [0.1, -0.1, 0.1, 0.1],
            "SH": [-0.1, 0.1, -0.1, None],
        }
    )
    result = compare_portfolios(returns, {"hedged": {"SPY": 0.5, "SH": 0.5}}, "SPY")
    row = result.row(0, named=True)
    assert row["observations"] == 3
    assert row["cumulative_return"] == pytest.approx(0.0)
    assert row["correlation_to_benchmark"] is None
    assert row["max_drawdown"] == pytest.approx(0.0)


def test_compare_portfolios_rejects_invalid_weights_and_missing_assets():
    returns = pl.DataFrame({"timestamp": [1, 2], "SPY": [0.01, 0.02]})
    with pytest.raises(ValueError, match="sum"):
        compare_portfolios(returns, {"bad": {"SPY": 1.2}}, "SPY")
    with pytest.raises(ValueError, match="missing"):
        compare_portfolios(returns, {"bad": {"MISSING": 1.0}}, "SPY")


def test_scenario_sensitivity_reports_portfolio_shock_and_contributions():
    result = scenario_sensitivity(
        {"balanced": {"SPY": 0.6, "SH": 0.4}},
        {"selloff": {"SPY": -0.2, "SH": 0.1}},
    )
    rows = result.to_dicts()
    assert len(rows) == 2
    assert {row["ticker"]: row["contribution"] for row in rows} == pytest.approx(
        {"SPY": -0.12, "SH": 0.04}
    )
    assert all(row["portfolio_shock"] == pytest.approx(-0.08) for row in rows)


def test_scenario_sensitivity_requires_all_shocks():
    with pytest.raises(ValueError, match="missing"):
        scenario_sensitivity({"p": {"SPY": 1.0}}, {"selloff": {"QQQ": -0.1}})


def test_compare_portfolios_reports_drawdown_and_inverse_market_relationship():
    returns = pl.DataFrame(
        {
            "timestamp": [1, 2, 3],
            "SPY": [0.1, -0.2, 0.1],
            "SH": [-0.1, 0.2, -0.1],
        }
    )
    row = compare_portfolios(returns, {"inverse": {"SH": 1.0}}, "SPY").row(0, named=True)
    assert row["correlation_to_benchmark"] == pytest.approx(-1.0)
    assert row["max_drawdown"] == pytest.approx(-0.1)
    assert row["concentration"] == pytest.approx(1.0)


def test_historical_returns_rejects_duplicate_and_bad_prices():
    duplicate = pl.DataFrame(
        {
            "timestamp": [1, 1],
            "ticker": ["SPY", "SPY"],
            "close": [100.0, 101.0],
        }
    )
    with pytest.raises(ValueError, match="duplicate"):
        historical_returns(duplicate)
    with pytest.raises(ValueError, match="positive"):
        historical_returns(
            duplicate.with_columns(pl.col("timestamp") + pl.int_range(pl.len())).with_columns(
                pl.lit(-1.0).alias("close")
            )
        )


def test_scenario_sensitivity_rejects_impossible_shock():
    with pytest.raises(ValueError, match=">= -1"):
        scenario_sensitivity({"p": {"SPY": 1.0}}, {"bad": {"SPY": -1.1}})
