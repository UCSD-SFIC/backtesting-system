"""File based commands for paper allocations and scenario research."""

from __future__ import annotations

import json
import math
from pathlib import Path

from experiments.store import list_runs
from paper.csv import read_holdings_csv, write_rebalance_csv
from paper.rebalance import rebalance
from research import scenario_sensitivity


def _read_mapping(path: str, *, nested: bool = False) -> dict:
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    def valid_numbers(items: dict) -> bool:
        return all(
            isinstance(key, str) and key.strip()
            and isinstance(number, (int, float)) and not isinstance(number, bool)
            and math.isfinite(number)
            for key, number in items.items()
        )
    if nested:
        if not all(isinstance(name, str) and name.strip() and isinstance(items, dict)
                   and valid_numbers(items) for name, items in value.items()):
            raise ValueError(f"{path} must map names to numeric ticker-weight objects")
    elif not valid_numbers(value):
        raise ValueError(f"{path} must map tickers to finite numbers")
    return value


def command_paper_rebalance(args) -> int:
    result = rebalance(
        _read_mapping(args.weights), _read_mapping(args.prices),
        read_holdings_csv(args.holdings), args.cash, args.cost_bps,
    )
    write_rebalance_csv(args.output, result)
    print(f"Saved paper recommendation to {args.output}")
    print(f"Leftover cash: ${result.ending_cash:,.2f}")
    print(f"Estimated costs: ${result.estimated_cost:,.2f}")
    return 0


def command_scenario_analysis(args) -> int:
    table = scenario_sensitivity(
        _read_mapping(args.portfolios, nested=True), _read_mapping(args.shocks, nested=True)
    )
    table.write_csv(args.output)
    print(f"Saved sensitivity table to {args.output}")
    return 0


def command_compare_runs(args) -> int:
    records = list_runs(args.run_dir)
    for record in records:
        total_return = record.metrics.get("total_return", 0.0)
        print(f"{record.run_id}  {record.review_state:<10}  return {total_return:.2%}")
    if not records:
        print("No saved runs")
    return 0
