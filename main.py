from dotenv import load_dotenv
import os
from polygon import RESTClient
from samplealpha import sampleAlpha
from backtest import (
    load_weight,
    load_data,
    backtest,
    plot_backtest,
    combine_ticker_histories,
)


if __name__ == "__main__":
    load_dotenv()
    api_key = os.getenv("POLYGON_API_KEY")
    if api_key is None:
        raise ValueError("POLYGON_API_KEY is not set in environment variables")
    tickers = ["SPY", "SH"]
    client = RESTClient(api_key)
    alpha = sampleAlpha("US", "day", tickers, "2024-01-01", "2024-12-06")

    history = load_data(
        client, tickers, timespan="day", from_time="2024-01-01", to_time="2024-12-06"
    )
    combined_history = combine_ticker_histories(history)

    weights = load_weight(alpha, combined_history)
    backtest_result = backtest(combined_history, weights, tickers)

    print(f"Total return: {backtest_result['overall_cumulative_return'].last():.02%}")
    plot_backtest(backtest_result, tickers)
