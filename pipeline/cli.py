"""
Command-line interface for configured backtests.

    python -m pipeline.cli run --config configs/sma_crossover.toml
    python -m pipeline.cli validate-data --config configs/sma_crossover.toml
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from typing import Any

from dotenv import load_dotenv
from pydantic import ValidationError

from data.cache import CachedDataProvider
from data.factory import PROVIDER_NAMES, create_data_provider, create_raw_provider
from data.validation import DataValidationError, validate_histories
from pipeline.backtest import run_backtest, summarize_backtest
from pipeline.config import RunConfig, load_config
from strategy.registry import build_strategy

# (metric key, label, format) in the order they are printed.
METRIC_ROWS = [
    ("total_return", "Total return", "{:.2%}"),
    ("compounding_annual_return", "Compounding annual return", "{:.2%}"),
    ("sharpe_ratio", "Sharpe ratio", "{:.3f}"),
    ("sortino_ratio", "Sortino ratio", "{:.3f}"),
    ("annualized_volatility", "Annualized volatility", "{:.2%}"),
    ("annual_variance", "Annual variance", "{:.4f}"),
    ("max_drawdown", "Max drawdown", "{:.2%}"),
    ("win_rate", "Win rate", "{:.2%}"),
    ("loss_rate", "Loss rate", "{:.2%}"),
    ("average_win", "Average win", "{:.2%}"),
    ("average_loss", "Average loss", "{:.2%}"),
    ("profit_loss_ratio", "Profit-loss ratio", "{:.2f}"),
    ("expectancy", "Expectancy", "{:.2%}"),
    ("beta", "Beta vs {benchmark}", "{:.3f}"),
    ("alpha", "Alpha vs {benchmark}", "{:.2%}"),
    ("periods_per_year", "Bars per year (annualization)", "{:.0f}"),
]

TRADING_ROWS = [
    ("rebalances", "Rebalances", "{:.0f}"),
    ("average_turnover", "Average turnover per rebalance", "{:.2%}"),
    ("annual_turnover", "Annual turnover", "{:.2%}"),
    ("total_cost", "Total simulated costs", "{:.2%}"),
    ("average_cash_weight", "Average cash weight", "{:.2%}"),
]


def format_metrics(metrics: dict[str, float], benchmark: str) -> str:
    rows = [
        (label.format(benchmark=benchmark), fmt.format(metrics[key]))
        for key, label, fmt in METRIC_ROWS + TRADING_ROWS
        if key in metrics
    ]
    width = max(len(label) for label, _ in rows)
    return "\n".join(f"{label:<{width}}  {value:>10}" for label, value in rows)


def _add_config_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", required=True, help="path to a TOML run config")
    parser.add_argument("--provider", choices=PROVIDER_NAMES, help="override data.provider")
    parser.add_argument("--tickers", help="comma-separated tickers; overrides the config")
    parser.add_argument("--start", help="override start date (YYYY-MM-DD)")
    parser.add_argument("--end", help="override end date (YYYY-MM-DD)")
    parser.add_argument("--refresh-cache", action="store_true", default=None, help="refetch data")


def _config_from_args(args: argparse.Namespace) -> RunConfig:
    overrides: dict[str, Any] = {
        "data.provider": args.provider,
        "start": args.start,
        "end": args.end,
        "data.refresh_cache": args.refresh_cache,
        "tickers": args.tickers.split(",") if args.tickers else None,
    }
    return load_config(args.config, overrides)


def _strategy_dates(config: RunConfig) -> tuple[str, str]:
    return config.start.isoformat(), config.end.isoformat()


def command_run(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    start, end = _strategy_dates(config)
    provider = create_data_provider(
        config.data.provider,
        cache_dir=config.data.cache_dir,
        refresh_cache=config.data.refresh_cache,
        validate=config.data.validate_data,
    )
    alpha = build_strategy(
        config.strategy.name,
        config.tickers,
        config.timespan,
        start,
        end,
        config.strategy.params,
    )

    # Fetch extra history before `start` so signals are ready on day one.
    fetch_start = (config.start - alpha.warmup_period()).isoformat()
    result = run_backtest(
        provider, alpha, config.timespan, fetch_start, end, cost_bps=config.execution.cost_bps
    )
    benchmark = config.benchmark or config.tickers[0]
    metrics = summarize_backtest(
        result, risk_free_rate=config.risk_free_rate, benchmark_ticker=benchmark
    )

    print(
        f"{config.strategy.name} on {', '.join(config.tickers)} "
        f"({config.timespan}, {start} to {end}, {config.data.provider})"
    )
    print(format_metrics(metrics, benchmark))
    holdings = getattr(alpha, "holdings", None)
    if holdings:
        timestamp, latest = holdings[-1]
        ranked = sorted(latest.items(), key=lambda item: -item[1])
        print(f"\nLatest target holdings ({timestamp:%Y-%m-%d}, {len(ranked)} names):")
        print(", ".join(f"{ticker} {weight:.1%}" for ticker, weight in ranked))

    if args.save_plot or not args.no_plot:
        import matplotlib.pyplot as plt

        from visualization.plots import create_backtest_figure

        # Large universes plot against the benchmark only.
        if len(config.tickers) > 5:
            figure = create_backtest_figure(result, [benchmark], show_components=False)
        else:
            figure = create_backtest_figure(result, config.tickers)
        if args.save_plot:
            figure.savefig(args.save_plot, dpi=150, bbox_inches="tight")
            print(f"Saved plot to {args.save_plot}")
        if not args.no_plot:
            plt.show()
        plt.close(figure)
    return 0


def command_validate_data(args: argparse.Namespace) -> int:
    config = _config_from_args(args)
    start, end = _strategy_dates(config)
    provider = create_raw_provider(config.data.provider)
    if config.data.cache_dir is not None:
        # Read whatever is cached, but never write data that has not passed checks.
        provider = CachedDataProvider(
            provider,
            config.data.cache_dir,
            refresh=config.data.refresh_cache,
            write=False,
        )

    histories = provider.get_history(config.tickers, config.timespan, start, end)
    issues = validate_histories(histories, config.timespan)

    for ticker, history in histories.items():
        print(f"{ticker}: {history.height} bars")
    for issue in issues:
        print(issue)

    errors = sum(issue.severity == "error" for issue in issues)
    warnings = len(issues) - errors
    print(f"{errors} errors, {warnings} warnings")
    return 1 if errors else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m pipeline.cli", description=(__doc__ or "").strip()
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    run = subcommands.add_parser("run", help="run a configured backtest and print metrics")
    _add_config_arguments(run)
    run.add_argument("--no-plot", action="store_true", help="do not open the plot window")
    run.add_argument("--save-plot", metavar="PATH", help="save the plot to an image file")
    run.set_defaults(handler=command_run)

    validate = subcommands.add_parser(
        "validate-data", help="fetch configured data and report quality issues"
    )
    _add_config_arguments(validate)
    validate.set_defaults(handler=command_validate_data)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except (ValidationError, DataValidationError, ValueError, FileNotFoundError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
