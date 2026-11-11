"""CSV import and export for paper portfolio artifacts."""

from __future__ import annotations

import csv
from pathlib import Path

from paper.rebalance import RebalanceResult


def read_holdings_csv(path: str | Path) -> dict[str, int]:
    """Read a CSV with ticker and whole-share holdings columns."""
    with Path(path).open(newline="") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames is None or not {"ticker", "shares"}.issubset(reader.fieldnames):
            raise ValueError("holdings CSV must include ticker and shares columns")
        holdings: dict[str, int] = {}
        for row in reader:
            ticker = (row["ticker"] or "").strip().upper()
            if not ticker:
                raise ValueError("holdings CSV has a blank ticker")
            if ticker in holdings:
                raise ValueError(f"duplicate holdings ticker: {ticker}")
            try:
                shares = int(row["shares"] or "")
            except ValueError as exc:
                raise ValueError(f"invalid shares for {ticker}") from exc
            if shares < 0:
                raise ValueError(f"negative shares for {ticker}")
            holdings[ticker] = shares
    return holdings


def write_rebalance_csv(path: str | Path, result: RebalanceResult) -> None:
    """Export a paper recommendation; this file is not a broker order."""
    with Path(path).open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(
            ("ticker", "current_shares", "target_shares", "delta_shares", "price", "estimated_cost")
        )
        for trade in result.trades:
            writer.writerow(
                (
                    trade.ticker,
                    trade.current_shares,
                    trade.target_shares,
                    trade.delta_shares,
                    trade.price,
                    trade.estimated_cost,
                )
            )
