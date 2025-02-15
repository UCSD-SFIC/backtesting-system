from polygon import RESTClient
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter
import matplotlib.dates as mdates
from dotenv import load_dotenv
import polars as pl
import os


def load_data(tickers, timespan, from_time, to_time):
    """
    Loads stock data from Polygon.io API for the given tickers.
    If the data is not cached, it will be downloaded and saved as a parquet file.
    Returns a dictionary of polars DataFrames, with the ticker as the key.
    """
    histories = {}
    cache_dir = "history_cache"
    for ticker in tickers:
        path = os.path.join(
            cache_dir, f"{ticker}-{timespan}-{from_time}-{to_time}.parquet"
        )
        try:
            df = pl.read_parquet(path)
            histories[ticker] = df
        except FileNotFoundError:
            print(f"Downloading {ticker} data")
            aggs = client.get_aggs(
                ticker=f"{ticker}",
                multiplier=1,
                timespan=timespan,
                from_=from_time,
                to=to_time,
            )
            df = pl.DataFrame(aggs)
            if not os.path.exists(cache_dir):
                os.makedirs(cache_dir)
            df.write_parquet(path)
            histories[ticker] = df
    return histories


def backtest(history, weights, tickers):
    """
    Backtests the given weights on the given stock data.
    Returns a DataFrame with the cumulative return and daily return.
    """
    backtest = weights.lazy()

    combined_history = None
    for ticker in tickers:
        df = (
            history[ticker]
            .lazy()
            .select(
                [
                    pl.from_epoch(pl.col("timestamp"), time_unit="ms").alias(
                        "timestamp"
                    ),
                    pl.col("close").alias(f"{ticker}_close"),
                    pl.col("close")
                    .pct_change()
                    .add(1)
                    .fill_null(1)
                    .alias(f"{ticker}_return"),
                ]
            )
        )
        if combined_history is None:
            combined_history = df
        else:
            combined_history = combined_history.join(df, on="timestamp", how="right")

    weights_lazy = (
        weights.lazy()
        .sort("timestamp")
        .select(
            pl.col("timestamp").alias("rebalance_date"),
            *[pl.col(ticker) for ticker in tickers],
        )
    )
    # Join weights with rebalance dates
    backtest = combined_history.join_asof(
        weights_lazy,
        left_on="timestamp",
        right_on="rebalance_date",
        strategy="backward",
    )

    # cumulative return within each rebalance period
    for ticker in tickers:
        backtest = backtest.with_columns(
            pl.col(f"{ticker}_return")
            .cum_prod()
            .over("rebalance_date")
            .alias(f"{ticker}_period_return")
        )

    backtest = backtest.with_columns(
        pl.sum_horizontal(
            [
                pl.col(f"{ticker}_period_return")
                .mul(pl.col(ticker))
                .alias(f"{ticker}_weighted_return")
                for ticker in tickers
            ]
        ).alias("period_total_weighted")
    )

    # previous period's last value
    aggregated_period = (
        backtest.group_by("rebalance_date")
        .agg(pl.col("period_total_weighted").last())
        .sort("rebalance_date")
        .with_columns(
            pl.col("period_total_weighted")
            .shift()
            .fill_null(1)
            .cum_prod()
            .alias("previous_period_last")
        )
    )
    backtest = backtest.join(aggregated_period, on="rebalance_date", how="right")

    # cumulative returns
    backtest = backtest.with_columns(
        [
            pl.col(f"{ticker}_return").cum_prod().alias(f"{ticker}_cumulative_return")
            for ticker in tickers
        ]
    ).with_columns(
        pl.col("period_total_weighted")
        .mul(pl.col("previous_period_last"))
        .alias("overall_cumulative_return"),
    )

    return backtest.collect()


def plot_backtest(backtest, tickers=[]):
    """
    Plots the cumulative return of the backtest.
    """
    plt.plot(
        backtest["timestamp"], backtest["overall_cumulative_return"], label="Portfolio"
    )
    for ticker in tickers:
        plt.plot(
            backtest["timestamp"],
            backtest[f"{ticker}_cumulative_return"],
            label=ticker,
        )
    plt.legend()
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
    stock1 = "NVDA"
    stock2 = "UVXY"
    tickers = [stock1, stock2]
    history = load_data(
        tickers, timespan="day", from_time="2024-01-01", to_time="2024-12-06"
    )
    # make weights dataframe with 0.5 for each stock and matching timestamps of history
    weights = pl.DataFrame(
        {
            stock1: [0.9, 0],
            stock2: [0.1, 1],
            "timestamp": pl.Series(
                ["01/01/2024 17:00:00.000", "06/06/2024 17:00:00.000"]
            ).str.strptime(pl.Datetime, "%d/%m/%Y %H:%M:%S%.3f"),
        }
    )
    backtest_result = backtest(history, weights, tickers)

    print(f"Total return: {backtest_result['overall_cumulative_return'].last():.02%}")
    plot_backtest(backtest_result)
