"""SEC EDGAR client: company directory, XBRL company facts, submissions.

Every SEC request in the app should go through this class so it shares one
rate limiter, one cache, and one fetch log. The filings workstream can call
`submissions(cik)` (filing list and company profile) and `get_json(...)` for
any other data.sec.gov / sec.gov JSON instead of writing a second fetcher.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from terminal.cache import SourceCache, SourceInfo
from terminal.config import Settings
from terminal.errors import DataUnavailableError, UpstreamError, UpstreamNotFoundError
from terminal.store import Company

PROVIDER = "SEC EDGAR"
COMPANY_DIRECTORY_URL = "https://www.sec.gov/files/company_tickers_exchange.json"
_DIRECTORY_FIELDS = ["cik", "name", "ticker", "exchange"]


def company_facts_url(cik: int) -> str:
    return f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"


def submissions_url(cik: int) -> str:
    return f"https://data.sec.gov/submissions/CIK{cik:010d}.json"


def filing_index_url(cik: int, accession: str) -> str | None:
    """Link to the filing's index page on sec.gov, e.g. for a provenance hover."""
    digits = accession.replace("-", "")
    if len(digits) != 18 or not digits.isdigit():
        return None
    return f"https://www.sec.gov/Archives/edgar/data/{cik}/{digits}/{accession}-index.htm"


def parse_company_directory(payload: Any) -> list[Company]:
    """Parse `company_tickers_exchange.json` into one row per ticker."""
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        raise UpstreamError("SEC company directory has an unexpected format")
    fields = payload.get("fields") or _DIRECTORY_FIELDS
    try:
        cik_at, name_at, ticker_at = (fields.index(name) for name in ("cik", "name", "ticker"))
    except ValueError as exc:
        raise UpstreamError("SEC company directory is missing expected fields") from exc
    exchange_at = fields.index("exchange") if "exchange" in fields else None

    companies: dict[str, Company] = {}
    for row in payload["data"]:
        try:
            ticker = str(row[ticker_at]).strip().upper()
            cik = int(row[cik_at])
            name = str(row[name_at]).strip()
        except (IndexError, TypeError, ValueError):
            continue
        if not ticker or ticker in companies:
            continue
        exchange = row[exchange_at] if exchange_at is not None and len(row) > exchange_at else None
        companies[ticker] = Company(ticker, cik, name, str(exchange) if exchange else None)
    if not companies:
        raise UpstreamError("SEC company directory contained no companies")
    return list(companies.values())


class SecClient:
    def __init__(self, cache: SourceCache, settings: Settings):
        self._cache = cache
        self._settings = settings

    def get_json(
        self,
        source_id: str,
        url: str,
        *,
        ttl: dt.timedelta,
        refresh: bool = False,
        expect: type | None = dict,
    ) -> tuple[Any, SourceInfo]:
        """Fetch any SEC JSON resource through the shared cache and rate limiter."""
        return self._cache.get_json(
            source_id, url, provider=PROVIDER, ttl=ttl, refresh=refresh, expect=expect
        )

    def company_directory(self, *, refresh: bool = False) -> tuple[list[Company], SourceInfo]:
        payload, source = self.get_json(
            "sec-company-directory",
            COMPANY_DIRECTORY_URL,
            ttl=self._settings.directory_ttl,
            refresh=refresh,
        )
        return parse_company_directory(payload), source

    def company_facts(
        self, cik: int, *, refresh: bool = False
    ) -> tuple[dict[str, Any], SourceInfo]:
        try:
            payload, source = self.get_json(
                f"sec-companyfacts-{cik:010d}",
                company_facts_url(cik),
                ttl=self._settings.company_facts_ttl,
                refresh=refresh,
            )
        except UpstreamNotFoundError as exc:
            raise DataUnavailableError(
                "The SEC has no XBRL financial data for this company"
            ) from exc
        return payload, source

    def submissions(self, cik: int, *, refresh: bool = False) -> tuple[dict[str, Any], SourceInfo]:
        """Company profile plus the recent-filings feed (10-K, 10-Q, 8-K, ...)."""
        try:
            payload, source = self.get_json(
                f"sec-submissions-{cik:010d}",
                submissions_url(cik),
                ttl=self._settings.submissions_ttl,
                refresh=refresh,
            )
        except UpstreamNotFoundError as exc:
            raise DataUnavailableError("The SEC has no filing record for this company") from exc
        return payload, source
