from __future__ import annotations

import matplotlib.pyplot as plt
from matplotlib.ticker import PercentFormatter
import polars as pl

from analytics.metrics import summarize_performance


def plot_backtest(backtest_df: pl.DataFrame, tickers: list[str]) -> None:
    metrics = summarize_performance(backtest_df)

    fig, (ax1, ax2, ax3) = plt.subplots(
        3,
        1,
        figsize=(14, 10),
        height_ratios=[2.0, 1.0, 1.0],
        sharex=True,
    )

    for ticker in tickers:
        ax1.plot(
            backtest_df["timestamp"],
            backtest_df[f"{ticker}_cumulative_return"],
            label=ticker,
            linewidth=1.2,
            alpha=0.75,
        )

    ax1.plot(
        backtest_df["timestamp"],
        backtest_df["overall_cumulative_return"],
        label="Portfolio",
        color="#005f73",
        linewidth=2.2,
    )
    ax1.set_title("Portfolio vs Components")
    ax1.set_ylabel("Cumulative Return")
    ax1.yaxis.set_major_formatter(PercentFormatter(1))
    ax1.grid(alpha=0.25)
    ax1.legend(loc="upper left")

    metrics_text = (
        f"Total Return: {metrics['total_return']:.2%}\n"
        f"Sharpe: {metrics['sharpe_ratio']:.2f}\n"
        f"Sortino: {metrics['sortino_ratio']:.2f}\n"
        f"Volatility: {metrics['annualized_volatility']:.2%}\n"
        f"Max Drawdown: {metrics['max_drawdown']:.2%}"
    )
    ax1.text(
        0.985,
        0.98,
        metrics_text,
        transform=ax1.transAxes,
        verticalalignment="top",
        horizontalalignment="right",
        fontsize=10,
        bbox={"facecolor": "white", "alpha": 0.85, "edgecolor": "#333"},
    )

    for ticker in tickers:
        ax2.plot(backtest_df["timestamp"], backtest_df[ticker], label=ticker, linewidth=1.3)
    ax2.set_title("Strategy Weights")
    ax2.set_ylabel("Weight")
    ax2.grid(alpha=0.25)
    ax2.legend(loc="upper left")

    drawdown = (
        backtest_df.select(
            [
                pl.col("overall_growth")
                .cum_max()
                .alias("running_peak"),
                ((pl.col("overall_growth") / pl.col("overall_growth").cum_max()) - 1).alias(
                    "drawdown"
                ),
            ]
        )
        .get_column("drawdown")
    )
    ax3.fill_between(
        backtest_df["timestamp"],
        drawdown,
        0,
        color="#bb3e03",
        alpha=0.35,
        label="Drawdown",
    )
    ax3.set_title("Portfolio Drawdown")
    ax3.set_ylabel("Drawdown")
    ax3.set_xlabel("Date")
    ax3.yaxis.set_major_formatter(PercentFormatter(1))
    ax3.grid(alpha=0.25)
    ax3.legend(loc="lower left")

    plt.tight_layout()
    plt.show()
