from polygon import RESTClient
import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter
import matplotlib.dates as mdates
from dotenv import load_dotenv
import polars as pl
import os
import numpy as np
from utils import sample_weight
from samplealpha import sampleAlpha
from datetime import datetime, timedelta
from utils import validate_weights
from time import time
from utils import timeit

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

@timeit
def backtest(history, weights, tickers):
    """
    Optimized backtesting function that handles historical data processing
    and weight calculations
    """
    # Pre-process historical data in one pass with unique timestamp
    first_ticker = tickers[0]
    base_df = (
        history[first_ticker]
        .lazy()
        .select([
            pl.from_epoch(pl.col("timestamp"), time_unit="ms")
            .cast(pl.Datetime("us"))
            .alias("timestamp"),
            pl.col("close")
            .pct_change()
            .add(1)
            .fill_null(1)
            .alias(f"{first_ticker}_return")
        ])
    )

    # Add returns for other tickers
    for ticker in tickers[1:]:
        base_df = base_df.join(
            history[ticker]
            .lazy()
            .select([
                pl.from_epoch(pl.col("timestamp"), time_unit="ms")
                .cast(pl.Datetime("us"))
                .alias("timestamp"),
                pl.col("close")
                .pct_change()
                .add(1)
                .fill_null(1)
                .alias(f"{ticker}_return")
            ]),
            on="timestamp",
            how="outer"
        )

    # Join weights more efficiently
    backtest = (
        base_df
        .join_asof(
            weights.lazy().sort("timestamp"),
            left_on="timestamp",
            right_on="timestamp",
            strategy="backward"
        )
        .with_columns([
            pl.col(ticker).forward_fill().alias(f"{ticker}_weight")
            for ticker in tickers
        ])
    )

    # Calculate returns in one pass
    backtest = backtest.with_columns([
        pl.col(f"{ticker}_return")
        .cum_prod()
        .over("timestamp")
        .alias(f"{ticker}_cumulative_return")
        for ticker in tickers
    ])

    # Calculate portfolio return
    backtest = backtest.with_columns(
        pl.sum_horizontal([
            pl.col(f"{ticker}_cumulative_return").mul(pl.col(f"{ticker}_weight"))
            for ticker in tickers
        ]).alias("overall_cumulative_return")
    )

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

@timeit
def load_weight(alpha):
    """
    Creates a weight DataFrame by iterating through time and updating weights
    """
    resolution_map = {
        "day": timedelta(days=1),
        "hour": timedelta(hours=1),
        "minute": timedelta(minutes=1)
    }
    freq = resolution_map.get(alpha.resolution, timedelta(days=1))

    # Create timestamps as Python list more efficiently
    start_date = datetime.strptime(alpha.start, "%Y-%m-%d")
    end_date = datetime.strptime(alpha.end, "%Y-%m-%d")
    num_days = (end_date - start_date).days + 1
    timestamps_list = [start_date + freq * i for i in range(num_days)]

    weights_data = {
        "timestamp": timestamps_list,
        **{ticker: [0.0] * len(timestamps_list) for ticker in alpha.get_ticker()}
    }
    timestamps = pl.DataFrame(weights_data).with_columns([
        pl.col("timestamp").cast(pl.Datetime("us"))
    ])

    tickers = alpha.get_ticker()
    weights_updates = []
    
    for ts in timestamps["timestamp"]:
        alpha.set_time(ts)
        current_weights = alpha.update()
        weights_updates.append(current_weights)

    for i, ticker in enumerate(tickers):
        timestamps = timestamps.with_columns(
            pl.when(pl.col("timestamp").is_in(timestamps["timestamp"]))
            .then(pl.Series([w[i] for w in weights_updates]))
            .otherwise(pl.col(ticker))
            .alias(ticker)
        )

    # Validate weights before returning
    validate_weights(timestamps, tickers)
        
    return timestamps, tickers

