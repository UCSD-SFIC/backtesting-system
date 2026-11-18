"""SQL storage for the research terminal: companies, fetch log, normalized facts.

SQLite by default (`terminal_data/terminal.sqlite3`); set
`TERMINAL_DATABASE_URL` to any SQLAlchemy URL to use something else. Raw
source payloads and price history stay on disk next to it; this database
holds what the API queries plus a record of when each source was last fetched.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
    case,
    create_engine,
    delete,
    func,
    or_,
    select,
)
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from terminal.statements import NormalizedFact, PeriodType


@dataclass(frozen=True)
class Company:
    ticker: str
    cik: int
    name: str
    exchange: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "ticker": self.ticker,
            "cik": self.cik,
            "name": self.name,
            "exchange": self.exchange,
        }


@dataclass(frozen=True)
class FetchRecord:
    source_id: str
    provider: str
    url: str
    fetched_at: dt.datetime
    payload_path: str | None
    last_error: str | None
    last_error_at: dt.datetime | None


@dataclass(frozen=True)
class IngestionRecord:
    cik: int
    source_fetched_at: dt.datetime
    definitions_hash: str
    fact_count: int


class _Base(DeclarativeBase):
    pass


class _CompanyRow(_Base):
    __tablename__ = "terminal_companies"

    ticker: Mapped[str] = mapped_column(String(16), primary_key=True)
    cik: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    exchange: Mapped[str | None] = mapped_column(String(32))


class _FetchRow(_Base):
    __tablename__ = "terminal_source_fetches"

    source_id: Mapped[str] = mapped_column(String(160), primary_key=True)
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)
    fetched_at: Mapped[str] = mapped_column(String(40), nullable=False)
    payload_path: Mapped[str | None] = mapped_column(String)
    last_error: Mapped[str | None] = mapped_column(Text)
    last_error_at: Mapped[str | None] = mapped_column(String(40))


class _IngestionRow(_Base):
    __tablename__ = "terminal_fact_ingestions"

    cik: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_fetched_at: Mapped[str] = mapped_column(String(40), nullable=False)
    definitions_hash: Mapped[str] = mapped_column(String(32), nullable=False)
    fact_count: Mapped[int] = mapped_column(Integer, nullable=False)


class _FactRow(_Base):
    __tablename__ = "terminal_financial_facts"
    __table_args__ = (
        UniqueConstraint("cik", "metric", "period_type", "fiscal_year", "fiscal_quarter"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    cik: Mapped[int] = mapped_column(Integer, index=True, nullable=False)
    metric: Mapped[str] = mapped_column(String(64), nullable=False)
    period_type: Mapped[str] = mapped_column(String(8), nullable=False)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    # 0 for annual rows so the unique constraint treats them as equal.
    fiscal_quarter: Mapped[int] = mapped_column(Integer, nullable=False)
    period_start: Mapped[str | None] = mapped_column(String(10))
    period_end: Mapped[str] = mapped_column(String(10), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    concept: Mapped[str] = mapped_column(String(200), nullable=False)
    accession: Mapped[str] = mapped_column(String(32), nullable=False)
    form: Mapped[str] = mapped_column(String(16), nullable=False)
    filed: Mapped[str] = mapped_column(String(10), nullable=False)
    derived: Mapped[bool] = mapped_column(Boolean, nullable=False)
    formula: Mapped[str | None] = mapped_column(Text)
    components: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)


def _iso(moment: dt.datetime) -> str:
    return moment.astimezone(dt.timezone.utc).isoformat()


def _moment(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value)


def _fact(row: _FactRow) -> NormalizedFact:
    period_type: PeriodType = "annual" if row.period_type == "annual" else "quarter"
    return NormalizedFact(
        metric=row.metric,
        period_type=period_type,
        fiscal_year=row.fiscal_year,
        fiscal_quarter=row.fiscal_quarter or None,
        period_start=dt.date.fromisoformat(row.period_start) if row.period_start else None,
        period_end=dt.date.fromisoformat(row.period_end),
        value=row.value,
        unit=row.unit,
        concept=row.concept,
        accession=row.accession,
        form=row.form,
        filed=dt.date.fromisoformat(row.filed),
        derived=row.derived,
        formula=row.formula,
        components=tuple(row.components),
    )


class TerminalStore:
    def __init__(self, database_url: str):
        url = make_url(database_url)
        if url.get_backend_name() == "sqlite" and url.database not in (None, "", ":memory:"):
            Path(url.database).parent.mkdir(parents=True, exist_ok=True)
        self._engine = create_engine(url)
        _Base.metadata.create_all(self._engine)

    def close(self) -> None:
        self._engine.dispose()

    # Company directory -------------------------------------------------

    def replace_companies(self, companies: list[Company]) -> None:
        with Session(self._engine) as session, session.begin():
            session.execute(delete(_CompanyRow))
            session.add_all(
                _CompanyRow(
                    ticker=company.ticker,
                    cik=company.cik,
                    name=company.name,
                    exchange=company.exchange,
                )
                for company in companies
            )

    def company_count(self) -> int:
        with Session(self._engine) as session:
            return session.scalar(select(func.count()).select_from(_CompanyRow)) or 0

    def get_company(self, ticker: str) -> Company | None:
        with Session(self._engine) as session:
            row = session.get(_CompanyRow, ticker.upper())
            return None if row is None else Company(row.ticker, row.cik, row.name, row.exchange)

    def search_companies(self, query: str, limit: int = 10) -> list[Company]:
        """Exact ticker first, then ticker prefix, then company-name matches."""
        text = query.strip().upper()
        if not text:
            return []
        name = func.upper(_CompanyRow.name)
        rank = case(
            (_CompanyRow.ticker == text, 0),
            (_CompanyRow.ticker.startswith(text, autoescape=True), 1),
            (name.startswith(text, autoescape=True), 2),
            else_=3,
        )
        statement = (
            select(_CompanyRow)
            .where(
                or_(
                    _CompanyRow.ticker.startswith(text, autoescape=True),
                    name.contains(text, autoescape=True),
                )
            )
            .order_by(rank, _CompanyRow.ticker)
            .limit(limit)
        )
        with Session(self._engine) as session:
            return [
                Company(row.ticker, row.cik, row.name, row.exchange)
                for row in session.scalars(statement)
            ]

    # Fetch log ---------------------------------------------------------

    def record_fetch(
        self,
        source_id: str,
        *,
        provider: str,
        url: str,
        fetched_at: dt.datetime,
        payload_path: str | None,
    ) -> None:
        with Session(self._engine) as session, session.begin():
            row = session.get(_FetchRow, source_id)
            if row is None:
                row = _FetchRow(source_id=source_id)
                session.add(row)
            row.provider = provider
            row.url = url
            row.fetched_at = _iso(fetched_at)
            row.payload_path = payload_path
            row.last_error = None
            row.last_error_at = None

    def record_fetch_error(self, source_id: str, error: str, at: dt.datetime) -> None:
        """Note a failed refresh; only meaningful when an older copy exists."""
        with Session(self._engine) as session, session.begin():
            row = session.get(_FetchRow, source_id)
            if row is not None:
                row.last_error = error
                row.last_error_at = _iso(at)

    def get_fetch(self, source_id: str) -> FetchRecord | None:
        with Session(self._engine) as session:
            row = session.get(_FetchRow, source_id)
            if row is None:
                return None
            return FetchRecord(
                source_id=row.source_id,
                provider=row.provider,
                url=row.url,
                fetched_at=_moment(row.fetched_at),
                payload_path=row.payload_path,
                last_error=row.last_error,
                last_error_at=_moment(row.last_error_at) if row.last_error_at else None,
            )

    # Normalized facts --------------------------------------------------

    def replace_facts(
        self,
        cik: int,
        facts: list[NormalizedFact],
        *,
        source_fetched_at: dt.datetime,
        definitions_hash: str,
    ) -> None:
        with Session(self._engine) as session, session.begin():
            session.execute(delete(_FactRow).where(_FactRow.cik == cik))
            session.add_all(
                _FactRow(
                    cik=cik,
                    metric=fact.metric,
                    period_type=fact.period_type,
                    fiscal_year=fact.fiscal_year,
                    fiscal_quarter=fact.fiscal_quarter or 0,
                    period_start=fact.period_start.isoformat() if fact.period_start else None,
                    period_end=fact.period_end.isoformat(),
                    value=fact.value,
                    unit=fact.unit,
                    concept=fact.concept,
                    accession=fact.accession,
                    form=fact.form,
                    filed=fact.filed.isoformat(),
                    derived=fact.derived,
                    formula=fact.formula,
                    components=list(fact.components),
                )
                for fact in facts
            )
            row = session.get(_IngestionRow, cik)
            if row is None:
                row = _IngestionRow(cik=cik)
                session.add(row)
            row.source_fetched_at = _iso(source_fetched_at)
            row.definitions_hash = definitions_hash
            row.fact_count = len(facts)

    def get_ingestion(self, cik: int) -> IngestionRecord | None:
        with Session(self._engine) as session:
            row = session.get(_IngestionRow, cik)
            if row is None:
                return None
            return IngestionRecord(
                cik=row.cik,
                source_fetched_at=_moment(row.source_fetched_at),
                definitions_hash=row.definitions_hash,
                fact_count=row.fact_count,
            )

    def get_facts(
        self,
        cik: int,
        *,
        metrics: list[str] | None = None,
        period_type: PeriodType | None = None,
    ) -> list[NormalizedFact]:
        statement = select(_FactRow).where(_FactRow.cik == cik)
        if metrics is not None:
            statement = statement.where(_FactRow.metric.in_(metrics))
        if period_type is not None:
            statement = statement.where(_FactRow.period_type == period_type)
        statement = statement.order_by(
            _FactRow.metric, _FactRow.fiscal_year, _FactRow.fiscal_quarter
        )
        with Session(self._engine) as session:
            return [_fact(row) for row in session.scalars(statement)]
