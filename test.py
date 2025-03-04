import backtest
import polars as pl
import pytest


def test_backtest():
    days = pl.Series(
        [
            1704171600000,
            1704258000000,
            1704344400000,
            1704430800000,
        ]
    )
    a_prices = [1.0, 2.0, 4.0, 8.0]
    b_prices = [1.0, 0.5, 0.25, 0.125]

    # 2 days on each weight
    a_weights = [0.5, 0.2]
    b_weights = [0.5, 0.8]
    assert a_weights[0] + b_weights[0] == 1.0
    assert a_weights[1] + b_weights[1] == 1.0
    assert a_prices[0] == 1.0 and b_prices[0] == 1.0

    history = {
        "A": pl.DataFrame(
            {
                "timestamp": days,
                "close": a_prices,
            }
        ),
        "B": pl.DataFrame(
            {
                "timestamp": days,
                "close": b_prices,
            }
        ),
    }

    weights = pl.DataFrame(
        {
            "A": a_weights,
            "B": b_weights,
            "timestamp": pl.Series(
                ["01/01/2024 5:00:00", "04/01/2024 5:00:00"]
            ).str.strptime(pl.Datetime, "%d/%m/%Y %H:%M:%S"),
        }
    )
    tickers = ["A", "B"]
    result = backtest.backtest(history, weights, tickers)

    print("\nDebugging information:")
    print("Result columns:", result.columns)
    print("Result shape:", result.shape)
    print("Timestamps:", result["timestamp"].to_list())
    if "overall_cumulative_return" in result.columns:
        print("Returns:", result["overall_cumulative_return"].to_list())
    else:
        print("Missing overall_cumulative_return column")
        print("Available columns:", result.columns)

    day_1 = 1.0
    day_2 = a_weights[0] * a_prices[1] + b_weights[0] * b_prices[1]

    day_2_to_3 = (
        a_weights[1] * a_prices[2] / a_prices[1]
        + b_weights[1] * b_prices[2] / b_prices[1]
    )
    day_2_to_4 = (
        a_weights[1] * a_prices[3] / a_prices[1]
        + b_weights[1] * b_prices[3] / b_prices[1]
    )

    assert result["overall_cumulative_return"].to_list() == [
        day_1,
        day_2,
        day_2 * day_2_to_3,
        day_2 * day_2_to_4,
    ]
