from __future__ import annotations

import matplotlib

from engine.history import combine_ticker_histories
from pipeline.backtest import backtest
from visualization.plots import create_backtest_figure


matplotlib.use("Agg")


def test_create_backtest_figure_includes_metrics_panel(price_history, rebalance_weights):
    combined_history = combine_ticker_histories(price_history)
    result = backtest(combined_history, rebalance_weights, ["A", "B"])

    figure = create_backtest_figure(result, ["A", "B"])

    assert len(figure.axes) == 4
    assert figure.axes[0].get_title() == "Portfolio vs Components"
    assert figure.axes[1].get_title(loc="left") == "Performance Summary"


def test_create_backtest_figure_can_show_benchmark_only(price_history, rebalance_weights):
    combined_history = combine_ticker_histories(price_history)
    result = backtest(combined_history, rebalance_weights, ["A", "B"])

    figure = create_backtest_figure(result, ["A", "B"], show_components=False)
    top_chart = figure.axes[0]

    assert top_chart.get_title() == "Portfolio vs Benchmark"
    assert [line.get_label() for line in top_chart.lines] == ["A", "Portfolio"]
