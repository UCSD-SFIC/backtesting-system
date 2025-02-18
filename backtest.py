from polygon import RESTClient
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter
import matplotlib.dates as mdates
from dotenv import load_dotenv
import polars as pl
import os
import numpy as np
from weight import gen_weight

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
    Returns a DataFrame with the cumulative return, daily return, and weights.
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

    # Store weights for each ticker at each timestamp
    for ticker in tickers:
        backtest = backtest.with_columns(
            pl.col(ticker).forward_fill().alias(f"{ticker}_weight")
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
    ).with_columns([
        *[pl.col(f"{ticker}_weight").alias(ticker) for ticker in tickers],
        pl.col("period_total_weighted")
        .mul(pl.col("previous_period_last"))
        .alias("overall_cumulative_return"),
    ])
    
    return backtest.collect()


def calculate_sharpe_ratio(returns, risk_free_rate=0.02):
    """
    Calculate Sharpe ratio for the entire period using pct_change
    """
    # Calculate daily returns from cumulative returns
    daily_returns = returns.pct_change().drop_nulls()
    
    # Convert annual risk-free rate to daily
    daily_rf_rate = (1 + risk_free_rate) ** (1/252) - 1
    
    # Calculate excess returns
    excess_returns = daily_returns - daily_rf_rate
    
    # Calculate annualized Sharpe ratio
    annual_factor = 252
    sharpe_ratio = (
        excess_returns.mean() * annual_factor / 
        (excess_returns.std() * (annual_factor ** 0.5))
    )
    
    return sharpe_ratio

def plot_backtest(backtest, tickers=[]):
    # Create figure with two subplots
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(12, 8), height_ratios=[2, 1])
    
    # Calculate total return and Sharpe ratio
    total_return = backtest["overall_cumulative_return"].last()
    sharpe = calculate_sharpe_ratio(backtest["overall_cumulative_return"])
    
    # Plot cumulative returns
    ax1.plot(
        backtest["timestamp"], 
        backtest["overall_cumulative_return"], 
        label="Portfolio", 
        color='blue'
    )
    for ticker in tickers:
        ax1.plot(
            backtest["timestamp"],
            backtest[f"{ticker}_cumulative_return"],
            label=ticker,
        )
    
    # Add performance metrics as text (moved to upper right)
    metrics_text = f'Total Return: {total_return:.2%}\nSharpe Ratio: {sharpe:.2f}'
    ax1.text(0.98, 0.98, metrics_text,
             transform=ax1.transAxes,
             bbox=dict(facecolor='white', alpha=0.8, edgecolor='gray'),
             verticalalignment='top',
             horizontalalignment='right',  # Right align text
             fontsize=10)
    
    # Rest of the plotting code remains the same
    ax1.legend(loc='upper left')  # Legend stays in upper left
    ax1.set_title("Backtest Returns")
    ax1.yaxis.set_major_formatter(PercentFormatter(1))
    ax1.set_ylabel("Cumulative Return")
    
    # Plot weights on bottom subplot
    for ticker in tickers:
        ax2.plot(
            backtest["timestamp"], 
            backtest[ticker],
            label=ticker
        )
    ax2.set_title("Asset Weights")
    ax2.set_ylabel("Weight")
    ax2.set_xlabel("Date")
    ax2.grid(visible=True)
    ax2.legend()
    
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    load_dotenv()
    api_key = os.getenv("POLYGON_API_KEY")
    if api_key is None:
        raise ValueError("POLYGON_API_KEY is not set in environment variables")

    client = RESTClient(api_key)
    weights,tickers=gen_weight()
    history = load_data(
        tickers, timespan="day", from_time="2024-01-01", to_time="2024-12-06"
    )
    backtest_result = backtest(history, weights, tickers)

    print(f"Total return: {backtest_result['overall_cumulative_return'].last():.02%}")
    plot_backtest(backtest_result, tickers)
