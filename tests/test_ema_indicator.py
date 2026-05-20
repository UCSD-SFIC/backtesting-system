from __future__ import annotations

import polars as pl
import pytest

from engine.backtest_engine import BacktestEngine
from engine.history import combine_ticker_histories
from engine.weights import build_weight_frame
from strategy.ema_alpha import ExponentialMovingAverageAlpha


def test_engine_adds_exponential_moving_average_indicator(price_history):
    combined_history = combine_ticker_histories(price_history)
    engine = BacktestEngine(data_provider=None)

    result = engine.add_exponential_moving_average(combined_history, "A", window=3)

    assert "A_ema_3" in result.columns
    assert result["A_ema_3"].to_list() == pytest.approx(
        [1.0, 1.5, 2.75, 5.375]
    )


def test_engine_rejects_invalid_exponential_moving_average_window(price_history):
    combined_history = combine_ticker_histories(price_history)
    engine = BacktestEngine(data_provider=None)

    with pytest.raises(ValueError, match="window must be greater than 0"):
        engine.add_exponential_moving_average(combined_history, "A", window=0)


def test_ema_alpha_uses_engine_generated_indicators(price_history):
    combined_history = combine_ticker_histories(price_history)
    alpha = ExponentialMovingAverageAlpha(
        "US",
        "day",
        ["A", "B"],
        "2024-01-01",
        "2024-01-05",
        ema_window=3,
        regime_window=4,
    )
    engine = BacktestEngine(data_provider=None)

    history_with_indicators = engine.add_indicators(combined_history, alpha)
    weights = build_weight_frame(alpha, history_with_indicators)

    assert {"A_ema_3", "A_ema_4"}.issubset(set(history_with_indicators.columns))
    assert weights["A"].to_list() == [0.0, 0.0, 0.0]
    assert weights["B"].to_list() == [0.0, 0.0, 0.0]


def test_ema_alpha_buys_primary_when_price_dips_below_ema_in_bullish_regime():
    history = {
        "A": pl.DataFrame(
            {
                "timestamp": [
                    1704171600000,
                    1704258000000,
                    1704344400000,
                    1704430800000,
                    1704517200000,
                ],
                "close": [5.0, 15.0, 16.0, 12.0, 14.0],
            }
        ),
        "B": pl.DataFrame(
            {
                "timestamp": [
                    1704171600000,
                    1704258000000,
                    1704344400000,
                    1704430800000,
                    1704517200000,
                ],
                "close": [1.0, 1.0, 1.0, 1.0, 1.0],
            }
        ),
    }
    combined_history = combine_ticker_histories(history)
    alpha = ExponentialMovingAverageAlpha(
        "US",
        "day",
        ["A", "B"],
        "2024-01-01",
        "2024-01-05",
        ema_window=3,
        regime_window=4,
    )
    engine = BacktestEngine(data_provider=None)

    history_with_indicators = engine.add_indicators(combined_history, alpha)
    weights = build_weight_frame(alpha, history_with_indicators)

    assert weights["A"].to_list() == [0.0, 0.0, 0.0, 1.0]
    assert weights["B"].to_list() == [0.0, 0.0, 0.0, 0.0]


def test_ema_alpha_stays_in_cash_when_dip_happens_outside_bullish_regime():
    history = {
        "A": pl.DataFrame(
            {
                "timestamp": [
                    1704171600000,
                    1704258000000,
                    1704344400000,
                    1704430800000,
                    1704517200000,
                ],
                "close": [20.0, 18.0, 16.0, 14.0, 13.0],
            }
        ),
        "B": pl.DataFrame(
            {
                "timestamp": [
                    1704171600000,
                    1704258000000,
                    1704344400000,
                    1704430800000,
                    1704517200000,
                ],
                "close": [1.0, 1.0, 1.0, 1.0, 1.0],
            }
        ),
    }
    combined_history = combine_ticker_histories(history)
    alpha = ExponentialMovingAverageAlpha(
        "US",
        "day",
        ["A", "B"],
        "2024-01-01",
        "2024-01-05",
        ema_window=3,
        regime_window=4,
    )
    engine = BacktestEngine(data_provider=None)

    history_with_indicators = engine.add_indicators(combined_history, alpha)
    weights = build_weight_frame(alpha, history_with_indicators)

    assert weights["A"].to_list() == [0.0, 0.0, 0.0, 0.0]
    assert weights["B"].to_list() == [0.0, 0.0, 0.0, 0.0]
