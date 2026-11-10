from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import polars as pl

from data.schema import OHLCV_COLUMNS, PRICE_COLUMNS

Severity = Literal["error", "warning"]

# Largest calendar gap between consecutive bars that is still normal for the
# timespan (weekends plus a holiday). Intraday bars are not gap-checked because
# overnight and weekend closes make the expected gap irregular.
MAX_NORMAL_GAP_DAYS = {
    "day": 5,
    "week": 10,
    "month": 35,
}

# A single-bar move this large usually means a missing split adjustment or a
# bad print rather than a real return.
EXTREME_RETURN_THRESHOLD = 0.5


@dataclass(frozen=True)
class DataIssue:
    ticker: str
    check: str
    severity: Severity
    message: str
    count: int = 1

    def __str__(self) -> str:
        return f"[{self.severity}] {self.ticker} {self.check}: {self.message}"


class DataValidationError(ValueError):
    def __init__(self, issues: list[DataIssue]):
        self.issues = issues
        details = "\n".join(f"  {issue}" for issue in issues)
        super().__init__(f"Market data failed validation:\n{details}")


def validate_history(
    ticker: str,
    history: pl.DataFrame,
    timespan: str = "day",
) -> list[DataIssue]:
    """Check one ticker's OHLCV history and return every issue found."""
    missing = [column for column in OHLCV_COLUMNS if column not in history.columns]
    if missing:
        return [
            DataIssue(ticker, "missing_columns", "error", f"missing {missing}")
        ]
    if history.height == 0:
        return [DataIssue(ticker, "empty", "error", "no rows returned")]

    issues: list[DataIssue] = []

    def add(check: str, severity: Severity, count: int, message: str) -> None:
        if count > 0:
            issues.append(DataIssue(ticker, check, severity, message, count))

    for column in ["timestamp", "close"]:
        nulls = history[column].null_count()
        add("null_values", "error", nulls, f"{nulls} null {column} values")
    for column in ["open", "high", "low", "volume"]:
        nulls = history[column].null_count()
        add("null_values", "warning", nulls, f"{nulls} null {column} values")

    duplicates = history.height - history["timestamp"].n_unique()
    add("duplicate_timestamps", "error", duplicates, f"{duplicates} duplicate bars")

    unsorted = int((history["timestamp"].diff() < 0).sum())
    add("unsorted_timestamps", "error", unsorted, "timestamps are not ascending")

    non_positive = history.filter(
        pl.any_horizontal([pl.col(column) <= 0 for column in PRICE_COLUMNS])
    ).height
    add("non_positive_price", "error", non_positive, f"{non_positive} bars with price <= 0")

    negative_volume = int((history["volume"] < 0).sum())
    add("negative_volume", "error", negative_volume, f"{negative_volume} bars with volume < 0")

    inconsistent = history.filter(
        (pl.col("high") < pl.col("low"))
        | (pl.col("close") > pl.col("high"))
        | (pl.col("close") < pl.col("low"))
    ).height
    add(
        "inconsistent_ohlc",
        "warning",
        inconsistent,
        f"{inconsistent} bars where close is outside [low, high]",
    )

    extreme = int(
        (history["close"].pct_change().abs() > EXTREME_RETURN_THRESHOLD).sum()
    )
    add(
        "extreme_return",
        "warning",
        extreme,
        f"{extreme} bars moved more than {EXTREME_RETURN_THRESHOLD:.0%}; check split adjustment",
    )

    max_gap_days = MAX_NORMAL_GAP_DAYS.get(timespan)
    if max_gap_days is not None:
        max_gap_ms = max_gap_days * 24 * 60 * 60 * 1000
        gaps = int((history["timestamp"].sort().diff() > max_gap_ms).sum())
        add(
            "missing_bars",
            "warning",
            gaps,
            f"{gaps} gaps longer than {max_gap_days} days between bars",
        )

    return issues


def validate_histories(
    histories: dict[str, pl.DataFrame],
    timespan: str = "day",
) -> list[DataIssue]:
    issues: list[DataIssue] = []
    for ticker, history in histories.items():
        issues.extend(validate_history(ticker, history, timespan))
    return issues


def raise_for_errors(issues: list[DataIssue]) -> None:
    errors = [issue for issue in issues if issue.severity == "error"]
    if errors:
        raise DataValidationError(errors)
