from __future__ import annotations

import matplotlib.dates as mdates
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec
from matplotlib.ticker import PercentFormatter
import polars as pl

from analytics.metrics import summarize_performance


FIGURE_BG = "#f6f3ee"
PANEL_BG = "#fffdf8"
GRID_COLOR = "#d6d3d1"
TEXT_MAIN = "#1f2937"
TEXT_MUTED = "#6b7280"
PORTFOLIO_COLOR = "#0f766e"
ACCENT_COLOR = "#b45309"
METRIC_BORDER = "#d6d3d1"


def _style_axis(ax) -> None:
    ax.set_facecolor(PANEL_BG)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.spines["left"].set_color("#c4bfb7")
    ax.spines["bottom"].set_color("#c4bfb7")
    ax.tick_params(colors=TEXT_MUTED, labelsize=10)
    ax.title.set_color(TEXT_MAIN)
    ax.yaxis.label.set_color(TEXT_MAIN)
    ax.xaxis.label.set_color(TEXT_MAIN)
    ax.grid(color=GRID_COLOR, alpha=0.45, linewidth=0.8)


def create_backtest_figure(
    backtest_df: pl.DataFrame,
    tickers: list[str],
    show_components: bool = True,
):
    benchmark_ticker = tickers[0] if tickers else None
    metrics = summarize_performance(backtest_df, benchmark_ticker=benchmark_ticker)
    timestamps = backtest_df["timestamp"]
    portfolio_curve = backtest_df["overall_cumulative_return"]

    fig = plt.figure(figsize=(15.5, 9.6), facecolor=FIGURE_BG)
    grid = GridSpec(
        3,
        2,
        figure=fig,
        height_ratios=[1.55, 0.78, 0.72],
        width_ratios=[3.2, 1.45],
        wspace=0.12,
        hspace=0.24,
    )
    ax1 = fig.add_subplot(grid[0, 0])
    ax_metrics = fig.add_subplot(grid[:, 1])
    ax2 = fig.add_subplot(grid[1, :], sharex=ax1)
    ax3 = fig.add_subplot(grid[2, :], sharex=ax1)
    ax_metrics.set_facecolor(PANEL_BG)

    ticker_palette = [
        "#2563eb",
        "#7c3aed",
        "#ea580c",
        "#0891b2",
        "#dc2626",
        "#65a30d",
    ]
    ticker_colors = {
        ticker: ticker_palette[index % len(ticker_palette)]
        for index, ticker in enumerate(tickers)
    }

    component_tickers = tickers if show_components else tickers[:1]
    for ticker in component_tickers:
        if f"{ticker}_cumulative_return" in backtest_df.columns:
            ax1.plot(
                timestamps,
                backtest_df[f"{ticker}_cumulative_return"],
                label=ticker,
                color=ticker_colors[ticker],
                linewidth=1.5,
                alpha=0.82,
            )

    ax1.plot(
        timestamps,
        portfolio_curve,
        label="Portfolio",
        color=PORTFOLIO_COLOR,
        linewidth=2.8,
    )
    ax1.fill_between(
        timestamps,
        portfolio_curve,
        0,
        color=PORTFOLIO_COLOR,
        alpha=0.08,
    )
    ax1.set_title("Portfolio vs Components" if show_components else "Portfolio vs Benchmark")
    ax1.set_ylabel("Cumulative Return")
    ax1.yaxis.set_major_formatter(PercentFormatter(1))
    _style_axis(ax1)
    ax1.text(
        0.0,
        1.02,
        "Return Curve",
        transform=ax1.transAxes,
        fontsize=9,
        color=TEXT_MUTED,
        weight="bold",
    )
    if component_tickers:
        ax1.legend(
            loc="upper left",
            frameon=True,
            framealpha=0.95,
            facecolor=PANEL_BG,
            edgecolor=METRIC_BORDER,
        )
    ax1.scatter(
        timestamps[-1],
        portfolio_curve[-1],
        color=PORTFOLIO_COLOR,
        s=35,
        zorder=4,
    )
    ax1.annotate(
        f"{portfolio_curve[-1]:.1%}",
        xy=(timestamps[-1], portfolio_curve[-1]),
        xytext=(10, 0),
        textcoords="offset points",
        va="center",
        color=PORTFOLIO_COLOR,
        fontsize=10,
        weight="bold",
    )

    ax_metrics.set_title("Performance Summary", loc="left", pad=10)
    ax_metrics.axis("off")
    metric_rows = [
        ("Total Return", metrics["total_return"], f"{metrics['total_return']:.2%}"),
        ("Comp. Annual Return", metrics["compounding_annual_return"], f"{metrics['compounding_annual_return']:.2%}"),
        ("Sharpe Ratio", metrics["sharpe_ratio"], f"{metrics['sharpe_ratio']:.2f}"),
        ("Sortino Ratio", metrics["sortino_ratio"], f"{metrics['sortino_ratio']:.2f}"),
        ("Annualized Volatility", metrics["annualized_volatility"], f"{metrics['annualized_volatility']:.2%}"),
        ("Annual Variance", metrics["annual_variance"], f"{metrics['annual_variance']:.4f}"),
        ("Max Drawdown", metrics["max_drawdown"], f"{metrics['max_drawdown']:.2%}"),
        ("Win Rate", metrics["win_rate"], f"{metrics['win_rate']:.2%}"),
        ("Loss Rate", metrics["loss_rate"], f"{metrics['loss_rate']:.2%}"),
        ("Average Win", metrics["average_win"], f"{metrics['average_win']:.2%}"),
        ("Average Loss", metrics["average_loss"], f"{metrics['average_loss']:.2%}"),
        ("Profit-Loss Ratio", metrics["profit_loss_ratio"], f"{metrics['profit_loss_ratio']:.2f}"),
        ("Expectancy", metrics["expectancy"], f"{metrics['expectancy']:.2%}"),
        ("Alpha", metrics["alpha"], f"{metrics['alpha']:.2%}"),
        ("Beta", metrics["beta"], f"{metrics['beta']:.2f}"),
    ]
    ax_metrics.text(
        0.05,
        0.965,
        "Snapshot",
        transform=ax_metrics.transAxes,
        fontsize=10,
        color=TEXT_MUTED,
        weight="bold",
    )

    line_rows: list[str] = []
    for label, _, display_value in metric_rows:
        line_rows.append(f"{label}: {display_value}")

    summary_text = "\n".join(line_rows)
    ax_metrics.text(
        0.08,
        0.91,
        summary_text,
        transform=ax_metrics.transAxes,
        fontsize=9.2,
        color=TEXT_MAIN,
        va="top",
        linespacing=1.5,
        family="monospace",
    )

    ax_metrics.text(
        0.08,
        0.045,
        "Benchmark beta uses the first ticker in the universe.",
        transform=ax_metrics.transAxes,
        fontsize=8.3,
        color=TEXT_MUTED,
    )

    ax_metrics.text(
        0.06,
        0.02,
        (
            f"Generated from the current backtest run"
            + (f" | Beta benchmark: {benchmark_ticker}" if benchmark_ticker else "")
        ),
        transform=ax_metrics.transAxes,
        fontsize=8.2,
        color=TEXT_MUTED,
    )
    ax_metrics.add_patch(
        mpatches.FancyBboxPatch(
            (0.02, 0.02),
            0.96,
            0.97,
            transform=ax_metrics.transAxes,
            boxstyle="round,pad=0.018,rounding_size=0.03",
            facecolor=PANEL_BG,
            edgecolor=METRIC_BORDER,
            linewidth=1.0,
            zorder=-1,
        )
    )

    for ticker in tickers:
        ax2.plot(
            timestamps,
            backtest_df[ticker],
            label=ticker,
            color=ticker_colors[ticker],
            linewidth=1.8,
        )
    ax2.set_title("Strategy Weights")
    ax2.set_ylabel("Weight")
    ax2.set_ylim(-0.02, 1.02)
    _style_axis(ax2)
    ax2.text(
        0.0,
        1.02,
        "Allocation Path",
        transform=ax2.transAxes,
        fontsize=9,
        color=TEXT_MUTED,
        weight="bold",
    )
    ax2.legend(
        loc="upper left",
        ncol=min(3, max(1, len(tickers))),
        frameon=True,
        framealpha=0.95,
        facecolor=PANEL_BG,
        edgecolor=METRIC_BORDER,
    )

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
        timestamps,
        drawdown,
        0,
        color=ACCENT_COLOR,
        alpha=0.35,
        label="Drawdown",
    )
    ax3.plot(
        timestamps,
        drawdown,
        color=ACCENT_COLOR,
        linewidth=1.4,
    )
    ax3.set_title("Portfolio Drawdown")
    ax3.set_ylabel("Drawdown")
    ax3.set_xlabel("Date")
    ax3.yaxis.set_major_formatter(PercentFormatter(1))
    _style_axis(ax3)
    ax3.text(
        0.0,
        1.02,
        "Risk View",
        transform=ax3.transAxes,
        fontsize=9,
        color=TEXT_MUTED,
        weight="bold",
    )
    ax3.legend(
        loc="lower left",
        frameon=True,
        framealpha=0.95,
        facecolor=PANEL_BG,
        edgecolor=METRIC_BORDER,
    )
    ax3.xaxis.set_major_locator(mdates.AutoDateLocator())
    ax3.xaxis.set_major_formatter(mdates.ConciseDateFormatter(ax3.xaxis.get_major_locator()))
    for ax in (ax1, ax2):
        ax.tick_params(labelbottom=False)

    fig.suptitle(
        "Backtest Overview",
        x=0.055,
        y=0.985,
        ha="left",
        fontsize=17,
        color=TEXT_MAIN,
        weight="bold",
    )
    fig.text(
        0.055,
        0.958,
        "Portfolio returns, allocation shifts, and drawdown from the current strategy run",
        fontsize=9.5,
        color=TEXT_MUTED,
    )
    fig.subplots_adjust(left=0.07, right=0.97, top=0.87, bottom=0.08)
    return fig


def plot_backtest(
    backtest_df: pl.DataFrame,
    tickers: list[str],
    show_components: bool = True,
) -> None:
    fig = create_backtest_figure(backtest_df, tickers, show_components=show_components)
    plt.show()
    plt.close(fig)
