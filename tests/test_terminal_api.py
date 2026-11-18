"""End-to-end behaviour of the terminal service and its HTTP endpoints."""

from pathlib import Path

import httpx
import polars as pl
import pytest
from fastapi.testclient import TestClient
from terminal_fixtures import COST_CIK, K_2026, MILLION, Harness

from terminal import DataUnavailableError, TerminalService, UnknownTickerError
from terminal.__main__ import main
from terminal.sec import COMPANY_DIRECTORY_URL, company_facts_url
from terminal.statements import normalize_company_facts
from web.app import create_app

FACTS_URL = company_facts_url(COST_CIK)
FILING_URL = (
    "https://www.sec.gov/Archives/edgar/data/909832/000090983226000093/"
    "0000909832-26-000093-index.htm"
)


@pytest.fixture
def harness(tmp_path: Path):
    harness = Harness(tmp_path)
    yield harness
    harness.service.close()


@pytest.fixture
def client(harness: Harness, tmp_path: Path) -> TestClient:
    app = create_app(
        tmp_path / "configs", tmp_path / "runs", terminal_service=lambda: harness.service
    )
    return TestClient(app)


def test_search_finds_companies_by_ticker_or_name(client: TestClient, harness: Harness):
    body = client.get("/api/companies", params={"q": "cost"}).json()

    assert body["data"]["results"] == [
        {"ticker": "COST", "cik": COST_CIK, "name": "COSTCO WHOLESALE CORP /NEW",
         "exchange": "Nasdaq"},
        {"ticker": "CSTT", "cik": 1_000_001, "name": "Costar Test Holdings", "exchange": "NYSE"},
    ]
    source = body["meta"]["sources"][0]
    assert source["id"] == "sec-company-directory" and source["url"] == COMPANY_DIRECTORY_URL
    assert source["retrieved_at"] == harness.clock.now.isoformat() and not source["stale"]
    assert body["meta"]["warnings"] == []

    limited = client.get("/api/companies", params={"q": "c", "limit": 1}).json()
    assert len(limited["data"]["results"]) == 1
    assert client.get("/api/companies", params={"q": "zzzz"}).json()["data"]["results"] == []
    assert client.get("/api/companies").status_code == 422
    assert client.get("/api/companies", params={"q": "c", "limit": 500}).status_code == 422
    # The directory was downloaded once for all of the above.
    assert harness.sec.calls[COMPANY_DIRECTORY_URL] == 1
    assert set(harness.sec.user_agents) == {"SFIC Tests tester@ucsd.edu"}


def test_overview_combines_profile_price_and_sourced_fundamentals(client: TestClient):
    body = client.get("/api/companies/cost").json()
    data = body["data"]

    assert data["company"] == {
        "ticker": "COST",
        "cik": COST_CIK,
        "name": "COSTCO WHOLESALE CORP /NEW",
        "exchange": "Nasdaq",
        "sic": "5331",
        "sic_description": "Retail-Variety Stores",
        "fiscal_year_end": "08-30",
        "state_of_incorporation": "WA",
        "website": "https://www.costco.com",
        "entity_type": "operating",
        "edgar_url": "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=0000909832",
    }
    assert data["price"]["last_close"] == 1299.0
    assert data["price"]["last_close_date"] == "2026-11-17"
    assert data["price"]["source_id"] == "prices-yfinance-COST-day"

    cap = data["market_cap"]
    assert cap["value"] == 1299.0 * 443_000_000
    assert cap["derived"] and cap["formula"] == "last_close * shares_outstanding"
    assert [part["label"] for part in cap["components"]] == ["last_close", "shares_outstanding"]
    assert cap["components"][1]["as_of"] == "2026-09-29"
    assert cap["components"][1]["url"] == FILING_URL

    annual = data["latest_annual"]
    assert (annual["period"], annual["fiscal_year"], annual["period_end"]) == (
        "FY2026", 2026, "2026-08-30",
    )
    assert annual["metrics"]["net_income"] == {
        "period": "FY2026",
        "value": 9_226 * MILLION,
        "unit": "USD",
        "derived": False,
        "formula": None,
        "source": {
            "provider": "SEC EDGAR",
            "source_id": "sec-companyfacts-0000909832",
            "concept": "us-gaap:NetIncomeLoss",
            "accession": K_2026[0],
            "form": "10-K",
            "filed": "2026-10-07",
            "period_start": "2025-09-01",
            "period_end": "2026-08-30",
            "url": FILING_URL,
        },
        "components": [],
    }
    # Not in the fixture, so reported as missing rather than guessed.
    assert annual["metrics"]["long_term_debt"] == {
        "period": "FY2026", "value": None, "unit": "USD", "missing_reason": "not_reported",
    }
    assert {source["id"] for source in body["meta"]["sources"]} == {
        "sec-company-directory",
        "sec-submissions-0000909832",
        "prices-yfinance-COST-day",
        "sec-companyfacts-0000909832",
    }
    assert body["meta"]["warnings"] == []


def test_overview_degrades_by_section_instead_of_failing_or_faking(
    client: TestClient, harness: Harness
):
    harness.prices.error = ConnectionError("yahoo is down")
    del harness.sec.routes[f"https://data.sec.gov/submissions/CIK{COST_CIK:010d}.json"]

    body = client.get("/api/companies/COST").json()
    data = body["data"]
    assert data["price"] is None
    assert data["market_cap"] == {
        "value": None, "unit": "USD", "missing_reason": "price_unavailable",
    }
    assert data["company"]["sic"] is None and data["company"]["name"]
    assert data["latest_annual"]["metrics"]["revenue"]["value"] == 290_000 * MILLION
    assert [warning["code"] for warning in body["meta"]["warnings"]] == [
        "profile_unavailable", "price_unavailable",
    ]

    # A company with no XBRL facts at all: price loads, fundamentals are flagged.
    harness.prices.error = None
    body = client.get("/api/companies/CSTT").json()
    assert body["data"]["price"]["last_close"] == 1299.0
    assert body["data"]["latest_annual"] is None
    assert body["data"]["market_cap"]["missing_reason"] == "shares_not_reported"
    assert "financials_unavailable" in [w["code"] for w in body["meta"]["warnings"]]

    body = client.get("/api/companies/IFRS").json()
    assert body["data"]["latest_annual"] is None
    assert "financials_unavailable" in [w["code"] for w in body["meta"]["warnings"]]


def test_prices_endpoint_returns_bars_snapshot_and_source(client: TestClient, harness: Harness):
    body = client.get("/api/companies/COST/prices", params={"range": "1m"}).json()
    data = body["data"]

    assert (data["ticker"], data["interval"], data["range"]) == ("COST", "day", "1m")
    assert len(data["bars"]) == 32
    assert data["bars"][-1] == {
        "date": "2026-11-17", "open": 1298.0, "high": 1301.0, "low": 1296.0,
        "close": 1299.0, "volume": 1_000_000.0,
    }
    assert data["snapshot"]["previous_close"] == 1298.0
    assert body["meta"]["sources"][0]["provider"] == "Yahoo Finance (yfinance)"

    assert len(client.get("/api/companies/COST/prices").json()["data"]["bars"]) == 367
    assert client.get("/api/companies/COST/prices", params={"range": "2d"}).status_code == 422
    assert len(harness.prices.calls) == 1
    with pytest.raises(ValueError):
        harness.service.prices("COST", "2d")


def test_financials_table_has_a_source_or_reason_for_every_cell(client: TestClient):
    body = client.get(
        "/api/companies/COST/financials", params={"statement": "income", "period": "quarterly"}
    ).json()
    data = body["data"]

    assert (data["statement"], data["period"], data["cik"]) == ("income", "quarterly", COST_CIK)
    assert [period["key"] for period in data["periods"]] == [
        "FY2026-Q4", "FY2026-Q3", "FY2026-Q2", "FY2026-Q1", "FY2025-Q4", "FY2025-Q3",
    ]
    assert data["periods"][0] == {
        "key": "FY2026-Q4", "fiscal_year": 2026, "fiscal_quarter": 4,
        "period_start": "2026-05-11", "period_end": "2026-08-30",
    }
    rows = {row["metric"]: row for row in data["rows"]}
    assert list(rows)[:3] == ["revenue", "cost_of_revenue", "gross_profit"]
    assert rows["net_income"]["label"] == "Net income"

    q4 = rows["net_income"]["values"][0]
    assert q4["value"] == 2_998 * MILLION and q4["derived"]
    assert q4["formula"] == "FY2026 - YTD Q3 FY2026"
    assert [part["url"] for part in q4["components"]] == [
        FILING_URL,
        "https://www.sec.gov/Archives/edgar/data/909832/000090983226000051/"
        "0000909832-26-000051-index.htm",
    ]
    assert rows["eps_diluted"]["values"][0] == {
        "period": "FY2026-Q4", "value": None, "unit": "USD/shares",
        "missing_reason": "not_derivable",
    }
    assert rows["eps_diluted"]["values"][1]["value"] == 4.93
    assert rows["revenue"]["values"][0]["missing_reason"] == "not_reported"
    for row in data["rows"]:
        assert len(row["values"]) == len(data["periods"])
        for cell in row["values"]:
            assert ("source" in cell) != ("missing_reason" in cell)

    annual = client.get(
        "/api/companies/COST/financials", params={"statement": "balance", "limit": 1}
    ).json()["data"]
    assert [period["key"] for period in annual["periods"]] == ["FY2026"]
    assert annual["periods"][0]["period_start"] is None
    assets = {row["metric"]: row for row in annual["rows"]}["total_assets"]["values"][0]
    assert assets["value"] == 83_000 * MILLION and assets["source"]["period_start"] is None

    cash = client.get(
        "/api/companies/COST/financials", params={"statement": "cash_flow", "period": "annual"}
    ).json()["data"]
    assert [period["key"] for period in cash["periods"]] == ["FY2026", "FY2025"]
    assert client.get(
        "/api/companies/COST/financials", params={"statement": "equity"}
    ).status_code == 422


def test_errors_use_one_format_with_a_machine_readable_code(client: TestClient, harness: Harness):
    unknown = client.get("/api/companies/NOPE")
    assert unknown.status_code == 404
    assert unknown.json()["code"] == "unknown_ticker" and "NOPE" in unknown.json()["detail"]
    assert client.get("/api/companies/not a ticker!/prices").json()["code"] == "unknown_ticker"

    no_data = client.get("/api/companies/IFRS/financials")
    assert (no_data.status_code, no_data.json()["code"]) == (404, "data_unavailable")
    assert "IFRS" in no_data.json()["detail"]
    assert client.get("/api/companies/CSTT/financials").json()["code"] == "data_unavailable"

    harness.prices.error = ValueError("No data returned")
    assert client.get("/api/companies/CSTT/prices").json()["code"] == "data_unavailable"


def test_missing_configuration_and_throttling_are_reported_clearly(tmp_path: Path):
    unconfigured = Harness(tmp_path / "a", user_agent=None)
    client = TestClient(
        create_app(tmp_path / "c", tmp_path / "r", terminal_service=lambda: unconfigured.service)
    )
    response = client.get("/api/companies", params={"q": "cost"})
    assert (response.status_code, response.json()["code"]) == (503, "not_configured")
    assert "SEC_USER_AGENT" in response.json()["detail"]
    assert client.get("/api/companies/COST").status_code == 503
    assert sum(unconfigured.sec.calls.values()) == 0

    throttled = Harness(tmp_path / "b")
    throttled.sec.failure = httpx.Response(429, headers={"Retry-After": "3"})
    client = TestClient(
        create_app(tmp_path / "c", tmp_path / "r", terminal_service=lambda: throttled.service)
    )
    response = client.get("/api/companies/COST")
    assert (response.status_code, response.json()["code"]) == (503, "rate_limited")
    assert response.headers["retry-after"] == "3"
    assert throttled.sleeps.count(3) == 2  # honoured Retry-After between attempts

    throttled.sec.failure = httpx.Response(500)
    response = client.get("/api/companies/COST")
    assert (response.status_code, response.json()["code"]) == (502, "upstream_error")


def test_sources_are_refreshed_on_schedule_and_survive_outages(harness: Harness):
    service = harness.service
    service.overview("COST")
    service.financials("COST", "income")
    service.financials("COST", "cash_flow", "quarterly")
    assert harness.sec.calls[FACTS_URL] == 1

    harness.clock.advance(hours=13)
    assert service.financials("COST", "income")["meta"]["warnings"] == []
    assert harness.sec.calls[FACTS_URL] == 2

    # SEC goes down after the cache expires: keep serving, flag it as stale.
    harness.clock.advance(hours=13)
    harness.sec.failure = httpx.Response(503)
    stale = service.financials("COST", "income")
    assert stale["data"]["rows"][0]["values"][0]["value"] == 290_000 * MILLION
    assert stale["meta"]["sources"][0]["stale"]
    assert [warning["code"] for warning in stale["meta"]["warnings"]] == ["stale_source"]
    attempts = harness.sec.calls[FACTS_URL]
    service.financials("COST", "income")
    assert harness.sec.calls[FACTS_URL] == attempts  # no hammering while it is down

    harness.clock.advance(seconds=61)
    harness.sec.failure = None
    assert not service.financials("COST", "income")["meta"]["sources"][0]["stale"]
    assert service.search("cost")["meta"]["warnings"] == []


def test_restart_reuses_stored_data_and_renormalizes_when_definitions_change(
    harness: Harness, monkeypatch
):
    harness.service.financials("COST", "income")
    harness.service.close()

    restarted = harness.build()
    assert restarted.financials("COST", "income")["data"]["rows"][0]["values"][0]["value"]
    assert restarted.resolve("cost").cik == COST_CIK
    assert harness.sec.calls[FACTS_URL] == 1
    assert harness.sec.calls[COMPANY_DIRECTORY_URL] == 1

    normalized = []
    monkeypatch.setattr(
        "terminal.service.normalize_company_facts",
        lambda payload: normalized.append(1) or normalize_company_facts(payload),
    )
    harness.build().financials("COST", "income")
    assert normalized == []  # unchanged source and definitions: nothing to redo
    monkeypatch.setattr("terminal.service.definitions_hash", lambda: "changed")
    harness.build().financials("COST", "income")
    assert normalized == [1]
    restarted.close()


def test_ticker_resolution_accepts_dot_or_dash_share_classes(harness: Harness):
    assert harness.service.resolve("exm.b").ticker == "EXM-B"
    assert harness.service.resolve(" EXM-B ").ticker == "EXM-B"
    for bad in ("", "DROP TABLE", "../etc", "TOOLONGTICKER"):
        with pytest.raises(UnknownTickerError):
            harness.service.resolve(bad)


def test_facts_frame_gives_analysis_code_one_tidy_table(harness: Harness):
    frame = harness.service.facts_frame("COST")

    assert frame.schema["period_end"] == pl.Date and frame.schema["value"] == pl.Float64
    q4 = frame.filter((pl.col("metric") == "net_income") & (pl.col("period") == "FY2026-Q4"))
    assert q4["value"].to_list() == [2_998 * MILLION] and q4["derived"].to_list() == [True]
    quarters = frame.filter(
        (pl.col("metric") == "operating_cash_flow")
        & (pl.col("period_type") == "quarter")
        & (pl.col("fiscal_year") == 2026)
    )
    assert quarters["value"].sum() == 13_000 * MILLION
    with pytest.raises(DataUnavailableError):
        harness.service.facts_frame("CSTT")


def test_metric_definitions_endpoint_documents_the_mapping(client: TestClient, harness: Harness):
    body = client.get("/api/financial-metrics").json()
    revenue = body["data"]["metrics"][0]
    assert revenue["key"] == "revenue" and revenue["concepts"][0] == "us-gaap:Revenues"
    assert len(body["data"]["definitions_hash"]) == 16
    assert sum(harness.sec.calls.values()) == 0


def test_terminal_routes_do_not_disturb_the_dashboard(tmp_path: Path):
    created = []

    def factory() -> TerminalService:
        created.append(1)
        raise AssertionError("service must not be built until a terminal route is used")

    client = TestClient(
        create_app(tmp_path / "configs", tmp_path / "runs", terminal_service=factory)
    )
    assert client.get("/").status_code == 200
    assert client.get("/api/configs").json() == {"configs": []}
    assert client.get("/api/runs").json() == {"runs": []}
    assert created == []


def test_smoke_command_prints_a_summary_per_ticker(harness: Harness, capsys):
    assert main([], lambda: harness.service) == 2
    assert "usage" in capsys.readouterr().out

    assert main(["COST"], lambda: harness.service) == 0
    out = capsys.readouterr().out
    assert "COST  COSTCO WHOLESALE CORP /NEW  (CIK 909832)" in out
    assert "last close   1,299.00 on 2026-11-17" in out
    assert "net_income           9,226,000,000.00  FY2026  10-K 0000909832-26-000093" in out
    assert "quarters     FY2026-Q4, FY2026-Q3, FY2026-Q2, FY2026-Q1" in out
    assert "sec-companyfacts-0000909832" in out and "STALE" not in out

    harness.prices.error = ConnectionError("down")
    harness.clock.advance(hours=1)
    assert main(["COST", "NOPE"], lambda: harness.service) == 1
    out = capsys.readouterr().out
    assert "STALE" in out and "warning      stale_source" in out
    assert "NOPE  ERROR unknown_ticker" in out
