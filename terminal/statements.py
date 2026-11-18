"""Turn an SEC `companyfacts` payload into normalized annual/quarterly facts.

The raw payload is a pile of tagged values. Three things make it awkward:

1. `fy` / `fp` on each value describe the *filing* it came from, not the
   period the value covers (a FY2026 10-K also carries FY2025 comparatives
   labelled `fy=2026`). So periods are assigned from the dates instead.
2. 10-Qs report cash flow (and often income) year-to-date. Discrete quarters
   are derived by differencing, and every derived value says so and lists the
   values it was computed from.
3. Fiscal quarters are not always 13 weeks (Costco runs 12/12/12/16), so
   quarters are placed by where their end date falls in the fiscal year.

Nothing is invented: if a value is not reported and cannot be derived
exactly, it is simply absent.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Literal

from terminal.metrics import METRICS, SHARES_OUTSTANDING_CONCEPTS, MetricDefinition

PeriodType = Literal["annual", "quarter"]

ANNUAL_FORMS = frozenset({"10-K", "10-K/A", "10-KT", "10-KT/A", "20-F", "20-F/A", "40-F", "40-F/A"})
PERIODIC_FORMS = ANNUAL_FORMS | {"10-Q", "10-Q/A", "10-QT"}

_DAYS_PER_QUARTER = 365.25 / 4
_MIN_YEAR_DAYS, _MAX_YEAR_DAYS = 350, 380
_MIN_QUARTER_DAYS, _MAX_QUARTER_DAYS = 75, 125
_START_TOLERANCE_DAYS = 10
_END_TOLERANCE_DAYS = 3


@dataclass(frozen=True)
class RawFact:
    """One value exactly as the SEC reports it."""

    concept: str
    unit: str
    start: dt.date | None
    end: dt.date
    value: float
    accession: str
    form: str
    filed: dt.date
    fy: int | None

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1 if self.start else 0

    def source(self) -> dict[str, Any]:
        return {
            "concept": self.concept,
            "value": self.value,
            "period_start": self.start.isoformat() if self.start else None,
            "period_end": self.end.isoformat(),
            "accession": self.accession,
            "form": self.form,
            "filed": self.filed.isoformat(),
        }


@dataclass(frozen=True)
class NormalizedFact:
    """One metric for one fiscal period, with where it came from."""

    metric: str
    period_type: PeriodType
    fiscal_year: int
    fiscal_quarter: int | None
    period_start: dt.date | None
    period_end: dt.date
    value: float
    unit: str
    concept: str
    accession: str
    form: str
    filed: dt.date
    derived: bool = False
    formula: str | None = None
    components: tuple[dict[str, Any], ...] = ()

    @property
    def period_key(self) -> str:
        return period_key(self.fiscal_year, self.fiscal_quarter)


def period_key(fiscal_year: int, fiscal_quarter: int | None) -> str:
    return f"FY{fiscal_year}" if fiscal_quarter is None else f"FY{fiscal_year}-Q{fiscal_quarter}"


@dataclass(frozen=True)
class FiscalYear:
    label: int
    start: dt.date
    end: dt.date
    # True for the in-progress year after the latest 10-K, whose end is estimated.
    projected: bool = False


def _parse_date(value: Any) -> dt.date | None:
    if not isinstance(value, str):
        return None
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        return None


def _raw_facts(
    company_facts: dict[str, Any], taxonomy: str, concept: str, unit: str
) -> list[RawFact]:
    entries = (
        company_facts.get("facts", {})
        .get(taxonomy, {})
        .get(concept, {})
        .get("units", {})
        .get(unit, [])
    )
    facts: list[RawFact] = []
    for entry in entries:
        end = _parse_date(entry.get("end"))
        filed = _parse_date(entry.get("filed"))
        value = entry.get("val")
        if end is None or filed is None or isinstance(value, bool):
            continue
        if not isinstance(value, (int, float)):
            continue
        fy = entry.get("fy")
        facts.append(
            RawFact(
                concept=f"{taxonomy}:{concept}",
                unit=unit,
                start=_parse_date(entry.get("start")),
                end=end,
                value=float(value),
                accession=str(entry.get("accn", "")),
                form=str(entry.get("form", "")),
                filed=filed,
                fy=fy if isinstance(fy, int) else None,
            )
        )
    return facts


def _newer(candidate: RawFact, current: RawFact | None) -> bool:
    """Prefer the most recently filed value, which reflects any restatement."""
    if current is None:
        return True
    return (candidate.filed, candidate.accession) > (current.filed, current.accession)


class FiscalCalendar:
    """A company's fiscal years, worked out from the periods it has reported."""

    def __init__(self, years: list[FiscalYear], period_ends: frozenset[dt.date]):
        self.years = sorted(years, key=lambda year: year.end)
        self.period_ends = period_ends

    def locate(self, end: dt.date) -> tuple[FiscalYear, int] | None:
        """Return the fiscal year and quarter (1-4) that a period end falls in."""
        if not self.years:
            return None
        tolerance = dt.timedelta(days=_END_TOLERANCE_DAYS)
        if end < self.years[0].start - tolerance:
            return None

        year: FiscalYear | None = None
        for candidate in self.years:
            if end <= candidate.end + tolerance:
                if end < candidate.start - tolerance:
                    return None  # falls in a gap, e.g. a fiscal-year change
                year = candidate
                break
        if year is None:
            # After the latest 10-K: project forward one year at a time.
            previous = self.years[-1]
            for _ in range(3):
                projected = FiscalYear(
                    previous.label + 1,
                    previous.end + dt.timedelta(days=1),
                    previous.end + dt.timedelta(days=365),
                    projected=True,
                )
                if end <= projected.end + dt.timedelta(days=_START_TOLERANCE_DAYS):
                    year = projected
                    break
                previous = projected
        if year is None:
            return None

        quarter = 4 - round((year.end - end).days / _DAYS_PER_QUARTER)
        if not 1 <= quarter <= 4:
            return None
        return year, quarter


def build_fiscal_calendar(company_facts: dict[str, Any]) -> FiscalCalendar:
    """Find fiscal year ends from the ~12-month periods reported in annual filings."""
    support: dict[dt.date, set[str]] = defaultdict(set)
    starts: dict[dt.date, Counter[dt.date]] = defaultdict(Counter)
    first_filed: dict[dt.date, tuple[dt.date, int | None]] = {}
    period_ends: set[dt.date] = set()

    for concept, body in company_facts.get("facts", {}).get("us-gaap", {}).items():
        for unit in body.get("units", {}):
            for fact in _raw_facts(company_facts, "us-gaap", concept, unit):
                if fact.start is None or fact.form not in PERIODIC_FORMS:
                    continue
                period_ends.add(fact.end)
                if fact.form not in ANNUAL_FORMS:
                    continue
                if not _MIN_YEAR_DAYS <= fact.days <= _MAX_YEAR_DAYS:
                    continue
                support[fact.end].add(concept)
                starts[fact.end][fact.start] += 1
                known = first_filed.get(fact.end)
                if known is None or fact.filed < known[0]:
                    first_filed[fact.end] = (fact.filed, fact.fy)

    # A stray 12-month figure that does not end on the fiscal year end would
    # create a phantom year; keep the best-supported end in any 300-day window.
    accepted: list[dt.date] = []
    for end in sorted(support, key=lambda date: (-len(support[date]), date)):
        if all(abs((end - other).days) >= 300 for other in accepted):
            accepted.append(end)
    accepted.sort()
    if not accepted:
        return FiscalCalendar([], frozenset(period_ends))

    # The latest year is labelled by its own 10-K; earlier years count back
    # from it, which sidesteps the filing-based `fy` on comparative values.
    latest = accepted[-1]
    latest_label = first_filed[latest][1] or latest.year

    years: list[FiscalYear] = []
    for index, end in enumerate(accepted):
        label = latest_label - round((latest - end).days / 365.25)
        reported_start = starts[end].most_common(1)[0][0]
        start = reported_start
        if index > 0:
            after_previous = accepted[index - 1] + dt.timedelta(days=1)
            if abs((after_previous - reported_start).days) <= _START_TOLERANCE_DAYS:
                start = after_previous
        years.append(FiscalYear(label, start, end))
    return FiscalCalendar(years, frozenset(period_ends))


def _period_label(year: FiscalYear, quarter: int, *, ytd: bool) -> str:
    if ytd and quarter == 4:
        return f"FY{year.label}"
    prefix = "YTD " if ytd else ""
    return f"{prefix}Q{quarter} FY{year.label}"


def _component(role: str, label: str, fact: RawFact | NormalizedFact) -> dict[str, Any]:
    if isinstance(fact, RawFact):
        return {"role": role, "label": label, **fact.source()}
    return {
        "role": role,
        "label": label,
        "concept": fact.concept,
        "value": fact.value,
        "period_start": fact.period_start.isoformat() if fact.period_start else None,
        "period_end": fact.period_end.isoformat(),
        "accession": fact.accession,
        "form": fact.form,
        "filed": fact.filed.isoformat(),
        "derived": fact.derived,
    }


def _direct(
    metric: MetricDefinition,
    period_type: PeriodType,
    year: FiscalYear,
    quarter: int | None,
    fact: RawFact,
) -> NormalizedFact:
    return NormalizedFact(
        metric=metric.key,
        period_type=period_type,
        fiscal_year=year.label,
        fiscal_quarter=quarter,
        period_start=fact.start,
        period_end=fact.end,
        value=fact.value,
        unit=metric.unit,
        concept=fact.concept,
        accession=fact.accession,
        form=fact.form,
        filed=fact.filed,
    )


Key = tuple[int, int]  # (fiscal year label, quarter)


def _flow_series(
    metric: MetricDefinition, facts: list[RawFact], calendar: FiscalCalendar
) -> dict[tuple[PeriodType, int, int | None], NormalizedFact]:
    ytd: dict[Key, RawFact] = {}
    discrete: dict[Key, RawFact] = {}
    years: dict[int, FiscalYear] = {}

    for fact in facts:
        if fact.start is None:
            continue
        located = calendar.locate(fact.end)
        if located is None:
            continue
        year, quarter = located
        key = (year.label, quarter)
        years[year.label] = year
        is_quarter_length = _MIN_QUARTER_DAYS <= fact.days <= _MAX_QUARTER_DAYS
        from_year_start = abs((fact.start - year.start).days) <= _START_TOLERANCE_DAYS

        if from_year_start:
            if quarter == 4:
                plausible = _MIN_YEAR_DAYS <= fact.days <= _MAX_YEAR_DAYS
            else:
                plausible = abs(fact.days - quarter * _DAYS_PER_QUARTER) <= 35
            if not plausible:
                continue
            if _newer(fact, ytd.get(key)):
                ytd[key] = fact
            if quarter == 1 and is_quarter_length and _newer(fact, discrete.get(key)):
                discrete[key] = fact
        elif is_quarter_length and _newer(fact, discrete.get(key)):
            discrete[key] = fact

    series: dict[tuple[PeriodType, int, int | None], NormalizedFact] = {}
    for label, year in years.items():
        annual = ytd.get((label, 4))
        if annual is not None and not year.projected:
            series[("annual", label, None)] = _direct(metric, "annual", year, None, annual)

        quarters: dict[int, NormalizedFact] = {}
        for quarter in (1, 2, 3, 4):
            reported = discrete.get((label, quarter))
            if reported is not None:
                quarters[quarter] = _direct(metric, "quarter", year, quarter, reported)
                continue
            current = ytd.get((label, quarter))
            if current is None or not metric.additive or quarter == 1:
                continue

            current_label = _period_label(year, quarter, ytd=True)
            previous = ytd.get((label, quarter - 1))
            if previous is not None:
                previous_label = _period_label(year, quarter - 1, ytd=True)
                value = current.value - previous.value
                start = previous.end + dt.timedelta(days=1)
                formula = f"{current_label} - {previous_label}"
                components = (
                    _component("minuend", current_label, current),
                    _component("subtrahend", previous_label, previous),
                )
            elif all(earlier in quarters for earlier in range(1, quarter)):
                earlier_facts = [quarters[earlier] for earlier in range(1, quarter)]
                value = current.value - sum(fact.value for fact in earlier_facts)
                start = earlier_facts[-1].period_end + dt.timedelta(days=1)
                names = [f"Q{earlier} FY{label}" for earlier in range(1, quarter)]
                formula = f"{current_label} - ({' + '.join(names)})"
                components = (
                    _component("minuend", current_label, current),
                    *(
                        _component("subtrahend", name, fact)
                        for name, fact in zip(names, earlier_facts, strict=True)
                    ),
                )
            else:
                continue

            quarters[quarter] = NormalizedFact(
                metric=metric.key,
                period_type="quarter",
                fiscal_year=label,
                fiscal_quarter=quarter,
                period_start=start,
                period_end=current.end,
                value=value,
                unit=metric.unit,
                concept=current.concept,
                accession=current.accession,
                form=current.form,
                filed=current.filed,
                derived=True,
                formula=formula,
                components=components,
            )
        for quarter, fact in quarters.items():
            series[("quarter", label, quarter)] = fact
    return series


def _instant_series(
    metric: MetricDefinition, facts: list[RawFact], calendar: FiscalCalendar
) -> dict[tuple[PeriodType, int, int | None], NormalizedFact]:
    best: dict[Key, tuple[FiscalYear, RawFact]] = {}
    for fact in facts:
        # Only balances on a reporting-period end; skips cover-page dates etc.
        if fact.start is not None or fact.end not in calendar.period_ends:
            continue
        located = calendar.locate(fact.end)
        if located is None:
            continue
        year, quarter = located
        if quarter == 4 and not year.projected:
            if abs((year.end - fact.end).days) > _END_TOLERANCE_DAYS:
                continue
        key = (year.label, quarter)
        if key not in best or _newer(fact, best[key][1]):
            best[key] = (year, fact)

    series: dict[tuple[PeriodType, int, int | None], NormalizedFact] = {}
    for (label, quarter), (year, fact) in best.items():
        series[("quarter", label, quarter)] = _direct(metric, "quarter", year, quarter, fact)
        if quarter == 4 and not year.projected:
            series[("annual", label, None)] = _direct(metric, "annual", year, None, fact)
    return series


def normalize_company_facts(
    company_facts: dict[str, Any],
    metrics: Iterable[MetricDefinition] = METRICS,
) -> list[NormalizedFact]:
    """Normalize every known metric for every fiscal period the company reported."""
    calendar = build_fiscal_calendar(company_facts)
    normalized: list[NormalizedFact] = []
    for metric in metrics:
        merged: dict[tuple[PeriodType, int, int | None], NormalizedFact] = {}
        # Concepts are in priority order; a later one only fills periods the
        # earlier ones did not report.
        for concept in metric.concepts:
            facts = _raw_facts(company_facts, metric.taxonomy, concept, metric.unit)
            if not facts:
                continue
            build = _flow_series if metric.kind == "flow" else _instant_series
            for key, fact in build(metric, facts, calendar).items():
                merged.setdefault(key, fact)
        normalized.extend(merged.values())
    normalized.sort(
        key=lambda fact: (fact.metric, fact.period_type, fact.fiscal_year, fact.fiscal_quarter or 0)
    )
    return normalized


def latest_shares_outstanding(company_facts: dict[str, Any]) -> RawFact | None:
    """Most recent point-in-time share count, for market cap."""
    for taxonomy, concept in SHARES_OUTSTANDING_CONCEPTS:
        facts = [
            fact
            for fact in _raw_facts(company_facts, taxonomy, concept, "shares")
            if fact.value > 0
        ]
        if facts:
            return max(facts, key=lambda fact: (fact.end, fact.filed, fact.accession))
    return None
