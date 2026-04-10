from dotenv import load_dotenv
import os
from samplealpha import sampleAlpha
from backtest import (
    run_backtest,
    plot_backtest,
)
from data import PolygonDataProvider


if __name__ == "__main__":
    load_dotenv()
    api_key = os.getenv("POLYGON_API_KEY")
    if api_key is None:
        raise ValueError("POLYGON_API_KEY is not set in environment variables")
    tickers = ["SPY", "SH"]
    data_provider = PolygonDataProvider(api_key)
    alpha = sampleAlpha("US", "day", tickers, "2024-01-01", "2024-12-06")

    backtest_result = run_backtest(
        data_provider=data_provider,
        alpha=alpha,
        timespan="day",
        from_time="2024-01-01",
        to_time="2024-12-06",
    )

    print(f"Total return: {backtest_result['overall_cumulative_return'].last():.02%}")
    plot_backtest(backtest_result, tickers)
