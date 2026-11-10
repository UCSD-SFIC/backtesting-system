"""Historical ticker eligibility for point in time backtests."""

from __future__ import annotations

import csv
import datetime as dt
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Membership:
    ticker: str
    start_date: dt.date
    end_date: dt.date | None = None


@dataclass(frozen=True)
class PointInTimeUniverse:
    records: tuple[Membership, ...]

    def __post_init__(self) -> None:
        by_ticker: dict[str, list[Membership]] = {}
        normalized: list[Membership] = []
        for record in self.records:
            ticker = record.ticker.strip().upper()
            if not ticker:
                raise ValueError("membership ticker cannot be blank")
            if record.end_date is not None and record.end_date < record.start_date:
                raise ValueError(f"end_date precedes start_date for {ticker}")
            clean_record = Membership(ticker, record.start_date, record.end_date)
            by_ticker.setdefault(ticker, []).append(clean_record)
            normalized.append(clean_record)

        for ticker, periods in by_ticker.items():
            sorted_periods = sorted(periods, key=lambda item: item.start_date)
            for earlier, later in zip(sorted_periods, sorted_periods[1:], strict=False):
                if earlier.end_date is None or later.start_date <= earlier.end_date:
                    raise ValueError(f"membership periods overlap for {ticker}")
        object.__setattr__(self, "records", tuple(normalized))

    @classmethod
    def from_records(cls, records: Iterable[Membership]) -> PointInTimeUniverse:
        return cls(tuple(records))

    @classmethod
    def from_csv(cls, path: str | Path) -> PointInTimeUniverse:
        """Read ticker,start_date,end_date CSV; a blank end_date means active onward."""
        with Path(path).open(newline="") as file:
            reader = csv.DictReader(file)
            required = {"ticker", "start_date", "end_date"}
            if reader.fieldnames is None or not required.issubset(reader.fieldnames):
                raise ValueError("membership CSV needs ticker,start_date,end_date columns")
            records = [
                Membership(
                    ticker=row["ticker"] or "",
                    start_date=dt.date.fromisoformat(row["start_date"] or ""),
                    end_date=dt.date.fromisoformat(row["end_date"])
                    if row["end_date"]
                    else None,
                )
                for row in reader
            ]
        return cls.from_records(records)

    def eligible_tickers(self, on_date: dt.date) -> list[str]:
        """Return eligible tickers in first-appearance order, without duplicates."""
        tickers = dict.fromkeys(
            record.ticker
            for record in self.records
            if record.start_date <= on_date
            and (record.end_date is None or on_date <= record.end_date)
        )
        return list(tickers)
