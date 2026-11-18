import datetime as dt

from terminal_fixtures import (
    FY25,
    FY26,
    K_2025,
    K_2026,
    MILLION,
    Q1_2026,
    Q2_2026,
    Q3_2026,
    concept,
    costco_facts,
    entry,
)

from terminal.metrics import METRICS, METRICS_BY_KEY, definitions_hash, metrics_for
from terminal.statements import (
    build_fiscal_calendar,
    latest_shares_outstanding,
    normalize_company_facts,
)


def _index(facts):
    return {(fact.metric, fact.period_key): fact for fact in facts}


def test_fiscal_years_are_labelled_from_dates_not_filing_fy():
    calendar = build_fiscal_calendar(costco_facts())

    assert [(year.label, year.start, year.end) for year in calendar.years] == [
        (2025, dt.date(2024, 9, 2), dt.date(2025, 8, 31)),
        (2026, dt.date(2025, 9, 1), dt.date(2026, 8, 30)),
    ]
    # Costco's quarters are 12/12/12/16 weeks, not 13 each.
    assert calendar.locate(dt.date(2025, 11, 23))[1] == 1
    assert calendar.locate(dt.date(2026, 2, 15))[1] == 2
    assert calendar.locate(dt.date(2026, 5, 10))[1] == 3
    assert calendar.locate(dt.date(2026, 8, 30))[1] == 4
    assert calendar.locate(dt.date(2020, 1, 1)) is None


def test_annual_values_ignore_comparative_filing_labels():
    facts = _index(normalize_company_facts(costco_facts()))

    fy2025 = facts[("net_income", "FY2025")]
    assert fy2025.value == 8_099 * MILLION
    assert (fy2025.period_start, fy2025.period_end) == (dt.date(2024, 9, 2), dt.date(2025, 8, 31))
    # The FY2026 10-K repeats this number; the newest filing is the source.
    assert fy2025.accession == K_2026[0]
    assert facts[("net_income", "FY2026")].value == 9_226 * MILLION
    assert not fy2025.derived


def test_fourth_quarter_is_derived_from_year_minus_nine_months():
    facts = _index(normalize_company_facts(costco_facts()))

    assert facts[("net_income", "FY2026-Q1")].value == 2_001 * MILLION
    assert facts[("net_income", "FY2026-Q2")].value == 2_035 * MILLION
    assert facts[("net_income", "FY2026-Q3")].value == 2_192 * MILLION
    assert not facts[("net_income", "FY2026-Q2")].derived

    q4 = facts[("net_income", "FY2026-Q4")]
    assert q4.value == (9_226 - 6_228) * MILLION
    assert q4.derived and q4.formula == "FY2026 - YTD Q3 FY2026"
    assert (q4.period_start, q4.period_end) == (dt.date(2026, 5, 11), dt.date(2026, 8, 30))
    assert [(part["role"], part["value"], part["accession"]) for part in q4.components] == [
        ("minuend", 9_226 * MILLION, K_2026[0]),
        ("subtrahend", 6_228 * MILLION, Q3_2026[0]),
    ]

    # FY2025 only has nine-month and full-year figures in the fixture.
    assert facts[("net_income", "FY2025-Q3")].value == 1_903 * MILLION
    assert facts[("net_income", "FY2025-Q4")].value == (8_099 - 5_489) * MILLION
    assert ("net_income", "FY2025-Q1") not in facts
    assert ("net_income", "FY2025-Q2") not in facts


def test_year_to_date_cash_flow_is_split_into_quarters():
    facts = _index(normalize_company_facts(costco_facts()))

    values = [facts[("operating_cash_flow", f"FY2026-Q{q}")].value / MILLION for q in (1, 2, 3, 4)]
    assert values == [3_000, 3_500, 2_500, 4_000]
    assert not facts[("operating_cash_flow", "FY2026-Q1")].derived
    q2 = facts[("operating_cash_flow", "FY2026-Q2")]
    assert q2.derived and q2.formula == "YTD Q2 FY2026 - YTD Q1 FY2026"
    assert q2.period_start == dt.date(2025, 11, 24)
    assert sum(values) == facts[("operating_cash_flow", "FY2026")].value / MILLION


def test_per_share_figures_are_never_differenced():
    facts = _index(normalize_company_facts(costco_facts()))

    assert facts[("eps_diluted", "FY2026")].value == 20.77
    assert facts[("eps_diluted", "FY2026-Q3")].value == 4.93
    assert ("eps_diluted", "FY2026-Q4") not in facts
    assert not METRICS_BY_KEY["eps_diluted"].additive


def test_each_period_uses_the_first_concept_that_reported_it():
    facts = _index(normalize_company_facts(costco_facts()))

    assert facts[("revenue", "FY2026")].concept == "us-gaap:Revenues"
    assert facts[("revenue", "FY2025")].concept == "us-gaap:SalesRevenueNet"
    assert facts[("revenue", "FY2025")].value == 275_000 * MILLION


def test_balances_are_reported_for_year_end_and_each_quarter_end():
    facts = _index(normalize_company_facts(costco_facts()))

    assert facts[("total_assets", "FY2025")].value == 77_000 * MILLION
    assert facts[("total_assets", "FY2026")].value == 83_000 * MILLION
    assert facts[("total_assets", "FY2026-Q1")].value == 79_000 * MILLION
    assert facts[("total_assets", "FY2026-Q4")].value == 83_000 * MILLION
    assert facts[("total_assets", "FY2026")].period_start is None
    # The balance dated 2026-09-30 is not a reporting-period end.
    assert all(fact.value != 1 * MILLION for fact in facts.values())
    assert ("total_assets", "FY2027-Q1") not in facts


def test_restated_value_from_a_later_filing_wins():
    payload = costco_facts()
    payload["facts"]["us-gaap"]["NetIncomeLoss"]["units"]["USD"].append(
        entry(K_2026, FY25[1], 8_000 * MILLION, FY25[0])
    )
    payload["facts"]["us-gaap"]["NetIncomeLoss"]["units"]["USD"].remove(
        entry(K_2026, FY25[1], 8_099 * MILLION, FY25[0])
    )

    fact = _index(normalize_company_facts(payload))[("net_income", "FY2025")]
    assert (fact.value, fact.accession) == (8_000 * MILLION, K_2026[0])


def test_quarter_after_latest_annual_report_gets_next_fiscal_year():
    payload = costco_facts()
    q1_2027 = ("0000909832-26-000140", "10-Q", "2026-12-16", 2027, "Q1")
    payload["facts"]["us-gaap"]["NetIncomeLoss"]["units"]["USD"].append(
        entry(q1_2027, "2026-11-22", 2_100 * MILLION, "2026-08-31")
    )

    facts = _index(normalize_company_facts(payload))
    assert facts[("net_income", "FY2027-Q1")].value == 2_100 * MILLION
    assert ("net_income", "FY2027") not in facts


def test_quarter_is_derived_from_earlier_quarters_when_ytd_is_missing():
    payload = {
        "facts": {
            "us-gaap": {
                "NetIncomeLoss": concept(
                    "USD",
                    entry(Q1_2026, "2025-11-23", 10.0, "2025-09-01"),
                    entry(Q2_2026, "2026-02-15", 20.0, "2025-11-24"),
                    entry(Q3_2026, "2026-05-10", 30.0, "2026-02-16"),
                    entry(K_2026, FY26[1], 100.0, FY26[0]),
                )
            }
        }
    }

    q4 = _index(normalize_company_facts(payload))[("net_income", "FY2026-Q4")]
    assert q4.value == 40.0
    assert q4.formula == "FY2026 - (Q1 FY2026 + Q2 FY2026 + Q3 FY2026)"
    assert len(q4.components) == 4
    assert q4.period_start == dt.date(2026, 5, 11)


def test_stray_twelve_month_period_does_not_create_a_fiscal_year():
    payload = costco_facts()
    payload["facts"]["us-gaap"]["BusinessAcquisitionsProFormaRevenue"] = concept(
        "USD", entry(K_2026, "2026-06-30", 5.0, "2025-07-01")
    )

    assert [year.label for year in build_fiscal_calendar(payload).years] == [2025, 2026]


def test_unusable_payloads_produce_no_facts():
    assert normalize_company_facts({}) == []
    assert normalize_company_facts({"facts": {"ifrs-full": {}}}) == []
    junk = {
        "facts": {
            "us-gaap": {
                "NetIncomeLoss": {
                    "units": {
                        "USD": [
                            {"start": "2025-09-01", "end": "not a date", "val": 1},
                            {"start": "2025-09-01", "end": "2026-08-30", "val": "n/a",
                             "filed": "2026-10-07", "form": "10-K"},
                            {"start": "2025-09-01", "end": "2026-08-30", "val": True,
                             "filed": "2026-10-07", "form": "10-K"},
                        ]
                    }
                }
            }
        }
    }
    assert normalize_company_facts(junk) == []


def test_latest_shares_outstanding_prefers_cover_page_then_balance_sheet():
    shares = latest_shares_outstanding(costco_facts())
    assert shares is not None
    assert (shares.value, shares.end) == (443_000_000, dt.date(2026, 9, 29))

    payload = costco_facts()
    del payload["facts"]["dei"]
    assert latest_shares_outstanding(payload) is None
    payload["facts"]["us-gaap"]["CommonStockSharesOutstanding"] = concept(
        "shares", entry(K_2025, "2025-08-31", 444_500_000)
    )
    fallback = latest_shares_outstanding(payload)
    assert fallback is not None and fallback.concept == "us-gaap:CommonStockSharesOutstanding"


def test_metric_definitions_are_consistent():
    keys = [metric.key for metric in METRICS]
    assert len(keys) == len(set(keys))
    assert {metric.statement for metric in METRICS} == {"income", "balance", "cash_flow"}
    assert all(metric.concepts for metric in METRICS)
    assert all(metric.kind == "instant" for metric in metrics_for("balance"))
    assert definitions_hash() == definitions_hash()
    assert definitions_hash(METRICS[:3]) != definitions_hash()
    assert METRICS[0].to_dict()["concepts"][0] == "us-gaap:Revenues"
