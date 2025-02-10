from polygon import RESTClient
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter
import matplotlib.dates as mdates
from dotenv import load_dotenv
import polars as pl
import os


def load_data(tickers):
    """
    Loads stock data from Polygon.io API for the given tickers.
    If the data is not cached, it will be downloaded and saved as a parquet file.
    Returns a dictionary of polars DataFrames, with the ticker as the key.
    """
    histories = {}
    cache_dir = "history_cache"
    for ticker in tickers:
        path = os.path.join(cache_dir, f"{ticker}.parquet")
        try:
            df = pl.read_parquet(path)
            histories[ticker] = df
        except FileNotFoundError:
            print(f"Downloading {ticker} data")
            aggs = client.get_aggs(
                ticker=f"{ticker}",
                multiplier=1,
                timespan="year",
                from_="2000-01-01",
                to="2025-02-09",
            )
            df = pl.DataFrame(aggs)
            if not os.path.exists(cache_dir):
                os.makedirs(cache_dir)
            df.write_parquet(path)
            histories[ticker] = df
    return histories


def backtest(history, weights):
    """
    Backtests the given weights on the given stock data.
    Returns a DataFrame with the cumulative return and daily return.
    """
    backtest = weights.lazy()
    ticker_return_expressions = []  # daily return calculation for each stock

    # combine stock data into one DataFrame
    for ticker in tickers:
        backtest = backtest.join(
            history[ticker]
            .lazy()
            .select(["timestamp", pl.col("close").alias(f"{ticker}_close")]),
            on="timestamp",
            how="inner",
        )
        ticker_return_expressions.append(
            pl.col(f"{ticker}_close").pct_change().alias(f"{ticker}_return")
        )

    backtest = (
        backtest.with_columns(
            [
                pl.from_epoch(pl.col("timestamp"), time_unit="ms").alias("datetime"),
                *ticker_return_expressions,
            ]
        )
        .with_columns(
            pl.sum_horizontal(
                [pl.col(f"{ticker}_return") * pl.col(ticker) for ticker in tickers]
            ).alias("daily_return")
        )
        .with_columns(
            pl.col("daily_return").add(1).cum_prod().sub(1).alias("cumulative_return"),
        )
        .with_columns(
            [
                pl.col(f"{ticker}_return")
                .add(1)
                .cum_prod()
                .sub(1)
                .alias(f"{ticker}_cumulative_return")
                for ticker in tickers
            ]
        )
    )

    return backtest.collect()


def plot_backtest(backtest):
    """
    Plots the cumulative return of the backtest.
    """
    plt.plot(backtest["datetime"], backtest["cumulative_return"])
    plt.title("Backtest Returns")
    plt.gca().yaxis.set_major_formatter(PercentFormatter(1))
    plt.gca().xaxis.set_major_formatter(mdates.DateFormatter("%Y\n%b"))
    plt.gca().xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    plt.gca().xaxis.set_minor_locator(mdates.MonthLocator())
    plt.gca().grid(visible=True)
    plt.ylabel("Cumulative Return")
    plt.xlabel("Date")
    plt.show()


if __name__ == "__main__":
    load_dotenv()
    api_key = os.getenv("POLYGON_API_KEY")
    if api_key is None:
        raise ValueError("POLYGON_API_KEY is not set in environment variables")

    client = RESTClient(api_key)

    tickers = ["AAPL", "NVDA"]
    history = load_data(tickers)
    aapl = history["AAPL"]
    # make weights dataframe with 0.5 for each stock and matching timestamps of history
    weights = pl.DataFrame(
        {
            "AAPL": [0.5] * len(aapl),
            "NVDA": [0.5] * len(aapl),
            "timestamp": aapl["timestamp"],
        }
    )
    backtest_result = backtest(history, weights)
    print(f"Total return: {backtest_result['cumulative_return'].last():.003%}")
    plot_backtest(backtest_result)
