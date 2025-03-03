from dotenv import load_dotenv
import os
from polygon import RESTClient
from samplealpha import sampleAlpha
from utils import sample_weight
from backtest import load_weight, load_data, backtest, plot_backtest
import matplotlib.pyplot as plt


if __name__ == "__main__":
    load_dotenv()
    api_key = os.getenv("POLYGON_API_KEY")
    if (api_key is None):
        raise ValueError("POLYGON_API_KEY is not set in environment variables")

    client = RESTClient(api_key)
    alpha=sampleAlpha("US","day",sample_weight()[0],sample_weight()[1],"2024-01-01","2024-12-06")
    weights,tickers=load_weight(alpha)
    history = load_data(
        tickers, timespan="day", from_time="2024-01-01", to_time="2024-12-06"
    )
    backtest_result = backtest(history, weights, tickers)

    print(f"Total return: {backtest_result['overall_cumulative_return'].last():.02%}")
    plot_backtest(backtest_result, tickers)
