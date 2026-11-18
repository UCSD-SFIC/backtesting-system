"""Offline stand-ins for the SEC and price sources used by the terminal tests.

The Costco net income figures (periods, values, accession numbers, filing
dates) are copied from the SEC's XBRL API response for CIK 909832 /
us-gaap:NetIncomeLoss as retrieved on 2026-11-17, so the fiscal-calendar and
quarter logic is exercised against real 12/12/12/16-week reporting. Every
other number in this file is made up for testing and is not real data.
"""

from __future__ import annotations

import datetime as dt
import json
from collections import Counter
from pathlib import Path
from typing import Any

import httpx
import polars as pl

from data.providers import DataProvider
from terminal import Settings, TerminalService

COST_CIK = 909832
MILLION = 1_000_000

# accession, form, filed, fy, fp
K_2025 = ("0000909832-25-000101", "10-K", "2025-10-08", 2025, "FY")
K_2026 = ("0000909832-26-000093", "10-K", "2026-10-07", 2026, "FY")
Q3_2025 = ("0000909832-25-000033", "10-Q", "2025-06-05", 2025, "Q3")
Q1_2026 = ("0000909832-25-000169", "10-Q", "2025-12-17", 2026, "Q1")
Q2_2026 = ("0000909832-26-000029", "10-Q", "2026-03-11", 2026, "Q2")
Q3_2026 = ("0000909832-26-000051", "10-Q", "2026-06-03", 2026, "Q3")

FY25 = ("2024-09-02", "2025-08-31")
FY26 = ("2025-09-01", "2026-08-30")


def entry(
    filing: tuple[str, str, str, int, str], end: str, value: float, start: str | None = None
) -> dict[str, Any]:
    accession, form, filed, fy, fp = filing
    row: dict[str, Any] = {
        "end": end, "val": value, "accn": accession, "fy": fy, "fp": fp,
        "form": form, "filed": filed,
    }
    if start is not None:
        row = {"start": start, **row}
    return row


def concept(unit: str, *entries: dict[str, Any]) -> dict[str, Any]:
    return {"label": "test", "description": "test", "units": {unit: list(entries)}}


def costco_facts() -> dict[str, Any]:
    net_income = concept(
        "USD",
        # Real values (USD) from the SEC, including the comparative copies
        # that later filings repeat with their own fy/fp.
        entry(Q3_2025, "2025-05-11", 5_489 * MILLION, "2024-09-02"),
        entry(Q3_2026, "2025-05-11", 5_489 * MILLION, "2024-09-02"),
        entry(Q3_2025, "2025-05-11", 1_903 * MILLION, "2025-02-17"),
        entry(Q3_2026, "2025-05-11", 1_903 * MILLION, "2025-02-17"),
        entry(K_2025, FY25[1], 8_099 * MILLION, FY25[0]),
        entry(K_2026, FY25[1], 8_099 * MILLION, FY25[0]),
        entry(Q1_2026, "2025-11-23", 2_001 * MILLION, "2025-09-01"),
        entry(Q2_2026, "2026-02-15", 4_036 * MILLION, "2025-09-01"),
        entry(Q2_2026, "2026-02-15", 2_035 * MILLION, "2025-11-24"),
        entry(Q3_2026, "2026-05-10", 6_228 * MILLION, "2025-09-01"),
        entry(Q3_2026, "2026-05-10", 2_192 * MILLION, "2026-02-16"),
        entry(K_2026, FY26[1], 9_226 * MILLION, FY26[0]),
    )
    # Everything below is synthetic.
    operating_cash_flow = concept(
        "USD",
        entry(K_2025, FY25[1], 12_000 * MILLION, FY25[0]),
        entry(Q1_2026, "2025-11-23", 3_000 * MILLION, "2025-09-01"),
        entry(Q2_2026, "2026-02-15", 6_500 * MILLION, "2025-09-01"),
        entry(Q3_2026, "2026-05-10", 9_000 * MILLION, "2025-09-01"),
        entry(K_2026, FY26[1], 13_000 * MILLION, FY26[0]),
    )
    eps_diluted = concept(
        "USD/shares",
        entry(Q1_2026, "2025-11-23", 4.50, "2025-09-01"),
        entry(Q2_2026, "2026-02-15", 4.58, "2025-11-24"),
        entry(Q3_2026, "2026-05-10", 4.93, "2026-02-16"),
        entry(K_2026, FY26[1], 20.77, FY26[0]),
    )
    assets = concept(
        "USD",
        entry(K_2025, "2025-08-31", 77_000 * MILLION),
        entry(K_2026, "2025-08-31", 77_000 * MILLION),
        entry(Q1_2026, "2025-11-23", 79_000 * MILLION),
        entry(Q2_2026, "2026-02-15", 80_000 * MILLION),
        entry(Q3_2026, "2026-05-10", 81_000 * MILLION),
        entry(K_2026, "2026-08-30", 83_000 * MILLION),
        # Not a reporting-period end; must be ignored.
        entry(K_2026, "2026-09-30", 1 * MILLION),
    )
    return {
        "cik": COST_CIK,
        "entityName": "COSTCO WHOLESALE CORP /NEW",
        "facts": {
            "dei": {
                "EntityCommonStockSharesOutstanding": concept(
                    "shares",
                    entry(K_2025, "2025-09-30", 444_000_000),
                    entry(K_2026, "2026-09-29", 443_000_000),
                )
            },
            "us-gaap": {
                "NetIncomeLoss": net_income,
                "NetCashProvidedByUsedInOperatingActivities": operating_cash_flow,
                "EarningsPerShareDiluted": eps_diluted,
                "Assets": assets,
                # Revenue is tagged differently in each year to test fallback.
                "Revenues": concept("USD", entry(K_2026, FY26[1], 290_000 * MILLION, FY26[0])),
                "SalesRevenueNet": concept(
                    "USD", entry(K_2025, FY25[1], 275_000 * MILLION, FY25[0])
                ),
            },
        },
    }


def directory_payload() -> dict[str, Any]:
    return {
        "fields": ["cik", "name", "ticker", "exchange"],
        "data": [
            [COST_CIK, "COSTCO WHOLESALE CORP /NEW", "COST", "Nasdaq"],
            [1_000_001, "Costar Test Holdings", "CSTT", "NYSE"],
            [1_000_002, "Example Class B Corp", "EXM-B", "NYSE"],
            [1_000_003, "Foreign IFRS Filer PLC", "IFRS", "NYSE"],
            [1_000_004, "100% Organic_Foods Inc", "ORGN", None],
        ],
    }


def submissions_payload() -> dict[str, Any]:
    return {
        "cik": str(COST_CIK),
        "entityType": "operating",
        "sic": "5331",
        "sicDescription": "Retail-Variety Stores",
        "name": "COSTCO WHOLESALE CORP /NEW",
        "tickers": ["COST"],
        "exchanges": ["Nasdaq"],
        "website": "https://www.costco.com",
        "fiscalYearEnd": "0830",
        "stateOfIncorporation": "WA",
        "filings": {"recent": {"accessionNumber": [], "form": []}, "files": []},
    }


class FakeSec:
    """An httpx transport that plays the SEC and counts requests per URL."""

    def __init__(self) -> None:
        self.calls: Counter[str] = Counter()
        self.user_agents: list[str] = []
        self.routes: dict[str, Any] = {
            "https://www.sec.gov/files/company_tickers_exchange.json": directory_payload(),
            f"https://data.sec.gov/api/xbrl/companyfacts/CIK{COST_CIK:010d}.json": costco_facts(),
            f"https://data.sec.gov/submissions/CIK{COST_CIK:010d}.json": submissions_payload(),
            "https://data.sec.gov/api/xbrl/companyfacts/CIK0001000003.json": {
                "cik": 1_000_003, "entityName": "Foreign IFRS Filer PLC",
                "facts": {"ifrs-full": {}},
            },
        }
        # Set to an httpx.Response to make every request fail that way.
        self.failure: httpx.Response | None = None

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.calls[url] += 1
        self.user_agents.append(request.headers.get("user-agent", ""))
        if self.failure is not None:
            return self.failure
        if url not in self.routes:
            return httpx.Response(404)
        return httpx.Response(200, content=json.dumps(self.routes[url]).encode())

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)


class FakeClock:
    def __init__(self, start: dt.datetime | None = None) -> None:
        self.now = start or dt.datetime(2026, 11, 17, 20, 0, tzinfo=dt.timezone.utc)

    def __call__(self) -> dt.datetime:
        return self.now

    def advance(self, **kwargs: float) -> None:
        self.now += dt.timedelta(**kwargs)


def _epoch_ms(day: dt.date) -> int:
    return int(dt.datetime.combine(day, dt.time.min, tzinfo=dt.timezone.utc).timestamp() * 1000)


def price_frame(end: dt.date, days: int = 400, start_price: float = 900.0) -> pl.DataFrame:
    """Synthetic daily bars ending on `end`, rising one dollar a day."""
    dates = [end - dt.timedelta(days=days - 1 - index) for index in range(days)]
    closes = [start_price + index for index in range(days)]
    return pl.DataFrame(
        {
            "timestamp": [_epoch_ms(day) for day in dates],
            "open": [close - 1 for close in closes],
            "high": [close + 2 for close in closes],
            "low": [close - 3 for close in closes],
            "close": closes,
            "volume": [1_000_000.0] * days,
        }
    )


class FakePrices(DataProvider):
    name = "fake"

    def __init__(self, clock: FakeClock) -> None:
        self._clock = clock
        self.calls: list[tuple[list[str], str, str, str]] = []
        self.error: Exception | None = None

    def get_history(self, tickers, timespan, from_time, to_time):
        self.calls.append((list(tickers), timespan, from_time, to_time))
        if self.error is not None:
            raise self.error
        return {ticker: price_frame(self._clock.now.date()) for ticker in tickers}


class Harness:
    """A TerminalService wired to the fakes above, writing under `tmp_path`."""

    def __init__(self, tmp_path: Path, *, user_agent: str | None = "SFIC Tests tester@ucsd.edu"):
        self.clock = FakeClock()
        self.sec = FakeSec()
        self.prices = FakePrices(self.clock)
        self.sleeps: list[float] = []
        self.settings = Settings(sec_user_agent=user_agent, data_dir=tmp_path / "terminal_data")
        self.service = self.build()

    def build(self) -> TerminalService:
        return TerminalService(
            self.settings,
            transport=self.sec.transport(),
            price_provider_factory=lambda: self.prices,
            clock=self.clock,
            sleep=self.sleeps.append,
        )
