"""The research-terminal data service: one object the API and other code call.

    service = TerminalService()
    service.search("costco")
    service.overview("COST")
    service.prices("COST", "1y")
    service.financials("COST", "income", "quarterly")
    service.facts_frame("COST")      # Polars frame for analysis code

Every method returns `{"data": ..., "meta": {"generated_at", "sources",
"warnings"}}` (except `facts_frame`). Each number carries its own source.
When something is unavailable the value is `null` with a `missing_reason`;
nothing is filled in with sample data.
"""

from __future__ import annotations

import datetime as dt
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal

import httpx
import polars as pl

from terminal.cache import STALE_RETRY, Clock, KeyedLocks, SourceCache, SourceInfo, utc_now
from terminal.config import Settings
from terminal.errors import (
    ConfigurationError,
    DataUnavailableError,
    TerminalError,
    UnknownTickerError,
)
from terminal.http import HttpFetcher, RateLimiter
from terminal.metrics import (
    METRICS,
    METRICS_BY_KEY,
    Statement,
    definitions_hash,
    metrics_for,
)
from terminal.prices import RANGE_DAYS, PriceService, ProviderFactory, bars, slice_range, snapshot
from terminal.sec import SecClient, filing_index_url
from terminal.statements import (
    NormalizedFact,
    PeriodType,
    RawFact,
    latest_shares_outstanding,
    normalize_company_facts,
    period_key,
)
from terminal.store import Company, TerminalStore

Period = Literal["annual", "quarterly"]

DEFAULT_PERIODS = {"annual": 5, "quarterly": 8}
MAX_PERIODS = 40
OVERVIEW_METRICS = (
    "revenue",
    "operating_income",
    "net_income",
    "eps_diluted",
    "operating_cash_flow",
    "capital_expenditures",
    "cash_and_equivalents",
    "long_term_debt",
    "total_assets",
    "total_equity",
)
_TICKER = re.compile(r"[A-Z0-9][A-Z0-9.\-]{0,9}")


@dataclass(frozen=True)
class _FactsState:
    source: SourceInfo
    shares: RawFact | None
    checked_at: dt.datetime


class _Meta:
    """Collects the sources and warnings behind one response."""

    def __init__(self, clock: Clock):
        self._clock = clock
        self._sources: dict[str, SourceInfo] = {}
        self._warnings: list[dict[str, str]] = []

    def add(self, source: SourceInfo) -> None:
        self._sources[source.id] = source
        if source.stale:
            self.warn(
                "stale_source",
                f"{source.provider} could not be refreshed; showing data retrieved at "
                f"{source.retrieved_at.isoformat()}.",
            )

    def warn(self, code: str, message: str) -> None:
        self._warnings.append({"code": code, "message": message})

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self._clock().isoformat(),
            "sources": [source.to_dict() for source in self._sources.values()],
            "warnings": self._warnings,
        }


def _fiscal_year_end(value: Any) -> str | None:
    """SEC stores the fiscal year end as MMDD; return MM-DD."""
    if isinstance(value, str) and len(value) == 4 and value.isdigit():
        return f"{value[:2]}-{value[2:]}"
    return None


class TerminalService:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        transport: httpx.BaseTransport | None = None,
        price_provider_factory: ProviderFactory | None = None,
        clock: Clock = utc_now,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.settings = settings or Settings.from_env()
        self._clock = clock
        self.store = TerminalStore(self.settings.resolved_database_url())
        self._fetcher = HttpFetcher(
            self.settings.require_sec_user_agent,
            RateLimiter(self.settings.sec_requests_per_second, sleep=sleep),
            transport=transport,
            sleep=sleep,
        )
        cache = SourceCache(self.settings.data_dir / "raw", self.store, self._fetcher, clock=clock)
        # Shared SEC access for every workstream (see terminal/sec.py).
        self.sec = SecClient(cache, self.settings)
        self.price_service = PriceService(
            self.store,
            self.settings.data_dir,
            provider_name=self.settings.price_provider,
            provider_factory=price_provider_factory,
            ttl=self.settings.price_ttl,
            history_years=self.settings.price_history_years,
            clock=clock,
        )
        self._locks = KeyedLocks()
        self._directory: tuple[SourceInfo, dt.datetime] | None = None
        self._facts: dict[int, _FactsState] = {}

    def close(self) -> None:
        self._fetcher.close()
        self.store.close()

    # Shared building blocks -------------------------------------------

    def _fresh(self, source: SourceInfo, checked_at: dt.datetime, ttl: dt.timedelta) -> bool:
        now = self._clock()
        if source.stale:
            return now - checked_at < STALE_RETRY
        return now - source.retrieved_at < ttl

    def _ensure_directory(self) -> SourceInfo:
        with self._locks.get("directory"):
            if self._directory is not None and self._fresh(
                *self._directory, self.settings.directory_ttl
            ):
                return self._directory[0]
            companies, source = self.sec.company_directory()
            loaded = self._directory[0].retrieved_at if self._directory else None
            if loaded != source.retrieved_at or self.store.company_count() == 0:
                self.store.replace_companies(companies)
            self._directory = (source, self._clock())
            return source

    def resolve(self, ticker: str) -> Company:
        """Look a ticker up in the SEC directory (BRK.B and BRK-B both work)."""
        symbol = ticker.strip().upper()
        if not _TICKER.fullmatch(symbol):
            raise UnknownTickerError(f"'{ticker}' is not a valid ticker symbol")
        self._ensure_directory()
        company = self.store.get_company(symbol) or self.store.get_company(symbol.replace(".", "-"))
        if company is None:
            raise UnknownTickerError(
                f"{symbol} was not found in the SEC company directory. Only companies that "
                "file with the SEC are supported."
            )
        return company

    def _ensure_facts(self, company: Company) -> _FactsState:
        """Fetch company facts if due and keep the normalized table in sync."""
        with self._locks.get(f"facts-{company.cik}"):
            state = self._facts.get(company.cik)
            if state is not None and self._fresh(
                state.source, state.checked_at, self.settings.company_facts_ttl
            ):
                return state
            payload, source = self.sec.company_facts(company.cik)
            fingerprint = definitions_hash()
            ingestion = self.store.get_ingestion(company.cik)
            if (
                ingestion is None
                or ingestion.source_fetched_at != source.retrieved_at
                or ingestion.definitions_hash != fingerprint
            ):
                self.store.replace_facts(
                    company.cik,
                    normalize_company_facts(payload),
                    source_fetched_at=source.retrieved_at,
                    definitions_hash=fingerprint,
                )
            state = _FactsState(source, latest_shares_outstanding(payload), self._clock())
            self._facts[company.cik] = state
            return state

    def _fact_source(self, cik: int, fact: NormalizedFact) -> dict[str, Any]:
        return {
            "provider": "SEC EDGAR",
            "source_id": f"sec-companyfacts-{cik:010d}",
            "concept": fact.concept,
            "accession": fact.accession,
            "form": fact.form,
            "filed": fact.filed.isoformat(),
            "period_start": fact.period_start.isoformat() if fact.period_start else None,
            "period_end": fact.period_end.isoformat(),
            "url": filing_index_url(cik, fact.accession),
        }

    def _cell(self, cik: int, fact: NormalizedFact) -> dict[str, Any]:
        return {
            "period": fact.period_key,
            "value": fact.value,
            "unit": fact.unit,
            "derived": fact.derived,
            "formula": fact.formula,
            "source": self._fact_source(cik, fact),
            "components": [
                {**component, "url": filing_index_url(cik, str(component.get("accession", "")))}
                for component in fact.components
            ],
        }

    @staticmethod
    def _missing(metric: str, key: str, fiscal_quarter: int | None) -> dict[str, Any]:
        definition = METRICS_BY_KEY[metric]
        not_derivable = fiscal_quarter == 4 and not definition.additive
        return {
            "period": key,
            "value": None,
            "unit": definition.unit,
            "missing_reason": "not_derivable" if not_derivable else "not_reported",
        }

    # Public API --------------------------------------------------------

    def metric_definitions(self) -> dict[str, Any]:
        return {
            "data": {
                "definitions_hash": definitions_hash(),
                "metrics": [metric.to_dict() for metric in METRICS],
            },
            "meta": _Meta(self._clock).to_dict(),
        }

    def search(self, query: str, limit: int = 10) -> dict[str, Any]:
        meta = _Meta(self._clock)
        meta.add(self._ensure_directory())
        results = self.store.search_companies(query, max(1, min(limit, 50)))
        return {
            "data": {"query": query, "results": [company.to_dict() for company in results]},
            "meta": meta.to_dict(),
        }

    def prices(self, ticker: str, range_name: str = "1y") -> dict[str, Any]:
        if range_name not in RANGE_DAYS:
            raise ValueError(f"range must be one of: {', '.join(RANGE_DAYS)}")
        company = self.resolve(ticker)
        meta = _Meta(self._clock)
        history, source = self.price_service.history(company.ticker)
        meta.add(source)
        window = slice_range(history, range_name, self._clock().date())
        return {
            "data": {
                "ticker": company.ticker,
                "interval": "day",
                "range": range_name,
                "currency": "USD",
                "snapshot": snapshot(history),
                "bars": bars(window),
            },
            "meta": meta.to_dict(),
        }

    def financials(
        self,
        ticker: str,
        statement: Statement,
        period: Period = "annual",
        limit: int | None = None,
    ) -> dict[str, Any]:
        company = self.resolve(ticker)
        meta = _Meta(self._clock)
        meta.add(self._ensure_facts(company).source)

        period_type: PeriodType = "annual" if period == "annual" else "quarter"
        definitions = metrics_for(statement)
        facts = self.store.get_facts(
            company.cik, metrics=[metric.key for metric in definitions], period_type=period_type
        )
        if not facts and not self.store.get_facts(company.cik):
            raise DataUnavailableError(
                f"{company.ticker} has no US-GAAP financial statement data at the SEC. "
                "Foreign filers that report under IFRS are not supported yet."
            )

        by_cell = {(fact.metric, fact.fiscal_year, fact.fiscal_quarter): fact for fact in facts}
        spans: dict[tuple[int, int | None], dict[str, Any]] = {}
        for fact in facts:
            span = spans.setdefault(
                (fact.fiscal_year, fact.fiscal_quarter),
                {"period_start": None, "period_end": fact.period_end},
            )
            span["period_end"] = max(span["period_end"], fact.period_end)
            if fact.period_start is not None:
                earliest = span["period_start"] or fact.period_start
                span["period_start"] = min(earliest, fact.period_start)

        count = max(1, min(limit or DEFAULT_PERIODS[period], MAX_PERIODS))
        ordered = sorted(spans, key=lambda key: (key[0], key[1] or 0), reverse=True)[:count]
        periods = [
            {
                "key": period_key(year, quarter),
                "fiscal_year": year,
                "fiscal_quarter": quarter,
                "period_start": (
                    spans[(year, quarter)]["period_start"].isoformat()
                    if spans[(year, quarter)]["period_start"]
                    else None
                ),
                "period_end": spans[(year, quarter)]["period_end"].isoformat(),
            }
            for year, quarter in ordered
        ]
        rows = []
        for metric in definitions:
            values = []
            for year, quarter in ordered:
                fact = by_cell.get((metric.key, year, quarter))
                key = period_key(year, quarter)
                values.append(
                    self._cell(company.cik, fact)
                    if fact is not None
                    else self._missing(metric.key, key, quarter)
                )
            rows.append(
                {
                    "metric": metric.key,
                    "label": metric.label,
                    "unit": metric.unit,
                    "kind": metric.kind,
                    "values": values,
                }
            )
        return {
            "data": {
                "ticker": company.ticker,
                "cik": company.cik,
                "statement": statement,
                "period": period,
                "currency": "USD",
                "periods": periods,
                "rows": rows,
            },
            "meta": meta.to_dict(),
        }

    def overview(self, ticker: str) -> dict[str, Any]:
        """Company profile, price snapshot, market cap, and latest annual figures.

        Each section is independent: if prices are down the fundamentals still
        load, with a warning in `meta.warnings` and `null` where data is missing.
        """
        company = self.resolve(ticker)
        meta = _Meta(self._clock)
        meta.add(self._ensure_directory())

        profile: dict[str, Any] = {
            **company.to_dict(),
            "sic": None,
            "sic_description": None,
            "fiscal_year_end": None,
            "state_of_incorporation": None,
            "website": None,
            "entity_type": None,
            "edgar_url": (
                "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
                f"&CIK={company.cik:010d}"
            ),
        }
        try:
            submissions, source = self.sec.submissions(company.cik)
        except ConfigurationError:
            raise
        except TerminalError as exc:
            meta.warn("profile_unavailable", exc.message)
        else:
            meta.add(source)
            profile.update(
                name=submissions.get("name") or company.name,
                sic=submissions.get("sic") or None,
                sic_description=submissions.get("sicDescription") or None,
                fiscal_year_end=_fiscal_year_end(submissions.get("fiscalYearEnd")),
                state_of_incorporation=submissions.get("stateOfIncorporation") or None,
                website=submissions.get("website") or None,
                entity_type=submissions.get("entityType") or None,
            )

        price: dict[str, Any] | None = None
        price_source: SourceInfo | None = None
        try:
            history, price_source = self.price_service.history(company.ticker)
        except TerminalError as exc:
            meta.warn("price_unavailable", exc.message)
        else:
            meta.add(price_source)
            price = snapshot(history)
            if price is not None:
                price["source_id"] = price_source.id
                price["retrieved_at"] = price_source.retrieved_at.isoformat()

        shares: RawFact | None = None
        latest_annual: dict[str, Any] | None = None
        try:
            state = self._ensure_facts(company)
        except ConfigurationError:
            raise
        except TerminalError as exc:
            meta.warn("financials_unavailable", exc.message)
        else:
            meta.add(state.source)
            shares = state.shares
            facts = self.store.get_facts(
                company.cik, metrics=list(OVERVIEW_METRICS), period_type="annual"
            )
            if facts:
                year = max(fact.fiscal_year for fact in facts)
                current = {fact.metric: fact for fact in facts if fact.fiscal_year == year}
                key = period_key(year, None)
                latest_annual = {
                    "period": key,
                    "fiscal_year": year,
                    "period_end": max(fact.period_end for fact in current.values()).isoformat(),
                    "metrics": {
                        metric: (
                            self._cell(company.cik, current[metric])
                            if metric in current
                            else self._missing(metric, key, None)
                        )
                        for metric in OVERVIEW_METRICS
                    },
                }
            else:
                meta.warn(
                    "financials_unavailable",
                    f"{company.ticker} has no US-GAAP annual figures at the SEC.",
                )

        return {
            "data": {
                "company": profile,
                "price": price,
                "market_cap": self._market_cap(company, price, price_source, shares),
                "latest_annual": latest_annual,
            },
            "meta": meta.to_dict(),
        }

    def _market_cap(
        self,
        company: Company,
        price: dict[str, Any] | None,
        price_source: SourceInfo | None,
        shares: RawFact | None,
    ) -> dict[str, Any]:
        if price is None or price_source is None:
            return {"value": None, "unit": "USD", "missing_reason": "price_unavailable"}
        if shares is None:
            return {"value": None, "unit": "USD", "missing_reason": "shares_not_reported"}
        return {
            "value": price["last_close"] * shares.value,
            "unit": "USD",
            "derived": True,
            "formula": "last_close * shares_outstanding",
            "note": (
                f"Share count is as of {shares.end.isoformat()}, from the most recent filing "
                "that reports one. Companies with several share classes may be understated."
            ),
            "components": [
                {
                    "label": "last_close",
                    "value": price["last_close"],
                    "as_of": price["last_close_date"],
                    "source_id": price_source.id,
                },
                {
                    "label": "shares_outstanding",
                    "as_of": shares.end.isoformat(),
                    "source_id": f"sec-companyfacts-{company.cik:010d}",
                    "url": filing_index_url(company.cik, shares.accession),
                    **shares.source(),
                },
            ],
        }

    def facts_frame(self, ticker: str) -> pl.DataFrame:
        """All normalized facts for a company as a long Polars frame.

        One row per metric per fiscal period. Meant for analysis code (growth,
        margins, scores, valuation) so it never has to parse SEC data itself.
        """
        company = self.resolve(ticker)
        self._ensure_facts(company)
        facts = self.store.get_facts(company.cik)
        return pl.DataFrame(
            [
                {
                    "ticker": company.ticker,
                    "metric": fact.metric,
                    "period_type": fact.period_type,
                    "period": fact.period_key,
                    "fiscal_year": fact.fiscal_year,
                    "fiscal_quarter": fact.fiscal_quarter,
                    "period_start": fact.period_start,
                    "period_end": fact.period_end,
                    "value": fact.value,
                    "unit": fact.unit,
                    "derived": fact.derived,
                    "formula": fact.formula,
                    "concept": fact.concept,
                    "accession": fact.accession,
                    "form": fact.form,
                    "filed": fact.filed,
                }
                for fact in facts
            ],
            schema={
                "ticker": pl.String,
                "metric": pl.String,
                "period_type": pl.String,
                "period": pl.String,
                "fiscal_year": pl.Int64,
                "fiscal_quarter": pl.Int64,
                "period_start": pl.Date,
                "period_end": pl.Date,
                "value": pl.Float64,
                "unit": pl.String,
                "derived": pl.Boolean,
                "formula": pl.String,
                "concept": pl.String,
                "accession": pl.String,
                "form": pl.String,
                "filed": pl.Date,
            },
        )
