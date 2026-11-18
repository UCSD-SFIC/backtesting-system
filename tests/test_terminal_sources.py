"""HTTP fetching, the raw-payload cache, the SEC client and the SQL store."""

import datetime as dt
import json
from pathlib import Path

import httpx
import pytest
from terminal_fixtures import COST_CIK, FakeClock, FakeSec, costco_facts, directory_payload

from terminal.cache import SourceCache
from terminal.config import Settings
from terminal.errors import (
    ConfigurationError,
    DataUnavailableError,
    RateLimitedError,
    UpstreamError,
    UpstreamNotFoundError,
)
from terminal.http import HttpFetcher, RateLimiter
from terminal.sec import (
    COMPANY_DIRECTORY_URL,
    SecClient,
    filing_index_url,
    parse_company_directory,
)
from terminal.statements import normalize_company_facts
from terminal.store import Company, TerminalStore

URL = "https://data.sec.gov/test.json"


def _fetcher(handler, sleeps=None, **kwargs) -> HttpFetcher:
    sleeps = [] if sleeps is None else sleeps
    return HttpFetcher(
        lambda: "SFIC Tests tester@ucsd.edu",
        RateLimiter(1000, sleep=lambda _seconds: None),
        transport=httpx.MockTransport(handler),
        sleep=sleeps.append,
        **kwargs,
    )


def test_rate_limiter_spaces_calls_evenly():
    now = [100.0]
    sleeps: list[float] = []

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)
        now[0] += seconds

    limiter = RateLimiter(5, clock=lambda: now[0], sleep=sleep)
    for _ in range(3):
        limiter.acquire()
    assert sleeps == pytest.approx([0.2, 0.2])

    now[0] += 10  # idle time is not banked into a burst
    limiter.acquire()
    limiter.acquire()
    assert sleeps == pytest.approx([0.2, 0.2, 0.2])
    with pytest.raises(ValueError):
        RateLimiter(0)


def test_fetcher_identifies_itself_and_retries_transient_failures():
    responses = [httpx.Response(503), httpx.Response(500), httpx.Response(200, content=b"{}")]
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["user-agent"])
        return responses.pop(0)

    sleeps: list[float] = []
    assert _fetcher(handler, sleeps).get(URL) == b"{}"
    assert seen == ["SFIC Tests tester@ucsd.edu"] * 3
    assert sleeps == [0.5, 1.0]


def test_fetcher_reports_rate_limiting_with_retry_after():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "7"})

    sleeps: list[float] = []
    with pytest.raises(RateLimitedError) as caught:
        _fetcher(handler, sleeps).get(URL)
    assert caught.value.retry_after == 7
    assert caught.value.status_code == 503
    assert sleeps == [7, 7]


def test_fetcher_does_not_retry_permanent_failures():
    calls = []

    def respond(status: int):
        def handler(_request: httpx.Request) -> httpx.Response:
            calls.append(status)
            return httpx.Response(status, headers={"Retry-After": "soon"})

        return handler

    with pytest.raises(UpstreamNotFoundError):
        _fetcher(respond(404)).get(URL)
    with pytest.raises(UpstreamError, match="SEC_USER_AGENT"):
        _fetcher(respond(403)).get(URL)
    with pytest.raises(UpstreamError, match="HTTP 400"):
        _fetcher(respond(400)).get(URL)
    assert calls == [404, 403, 400]


def test_fetcher_gives_up_after_repeated_network_errors():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline", request=request)

    fetcher = _fetcher(handler, max_attempts=2)
    with pytest.raises(UpstreamError, match="failed after 2 attempts") as caught:
        fetcher.get(URL)
    assert not isinstance(caught.value, RateLimitedError)
    fetcher.close()


def test_missing_user_agent_fails_before_any_request():
    settings = Settings(sec_user_agent="no email here")
    calls = []
    fetcher = HttpFetcher(
        settings.require_sec_user_agent,
        RateLimiter(1000),
        transport=httpx.MockTransport(lambda request: calls.append(request) or httpx.Response(200)),
    )
    with pytest.raises(ConfigurationError, match="SEC_USER_AGENT"):
        fetcher.get(URL)
    assert calls == []


def test_settings_read_environment(monkeypatch):
    monkeypatch.setattr("terminal.config.load_dotenv", lambda: None)
    monkeypatch.setenv("SEC_USER_AGENT", "SFIC me@ucsd.edu")
    monkeypatch.setenv("TERMINAL_DATA_DIR", "elsewhere")
    monkeypatch.delenv("TERMINAL_DATABASE_URL", raising=False)
    settings = Settings.from_env()
    assert settings.require_sec_user_agent() == "SFIC me@ucsd.edu"
    assert settings.resolved_database_url() == "sqlite:///elsewhere/terminal.sqlite3"
    assert Settings(database_url="sqlite:///x.db").resolved_database_url() == "sqlite:///x.db"


@pytest.fixture
def sec_setup(tmp_path: Path):
    clock, sec = FakeClock(), FakeSec()
    store = TerminalStore(f"sqlite:///{tmp_path / 'db' / 'terminal.sqlite3'}")
    fetcher = HttpFetcher(
        lambda: "SFIC Tests tester@ucsd.edu",
        RateLimiter(1000, sleep=lambda _seconds: None),
        transport=sec.transport(),
        sleep=lambda _seconds: None,
    )
    cache = SourceCache(tmp_path / "raw", store, fetcher, clock=clock)
    client = SecClient(cache, Settings(sec_user_agent="SFIC Tests tester@ucsd.edu"))
    yield clock, sec, store, client
    store.close()


def test_cache_reuses_payload_until_ttl_then_refreshes(sec_setup):
    clock, sec, store, client = sec_setup

    companies, first = client.company_directory()
    assert [company.ticker for company in companies][:2] == ["COST", "CSTT"]
    assert first.retrieved_at == clock.now and not first.stale
    assert first.to_dict()["url"] == COMPANY_DIRECTORY_URL

    clock.advance(hours=23)
    _, again = client.company_directory()
    assert again.retrieved_at == first.retrieved_at
    assert sec.calls[COMPANY_DIRECTORY_URL] == 1

    clock.advance(hours=2)
    _, refreshed = client.company_directory()
    assert refreshed.retrieved_at == clock.now
    assert sec.calls[COMPANY_DIRECTORY_URL] == 2

    _, forced = client.company_directory(refresh=True)
    assert sec.calls[COMPANY_DIRECTORY_URL] == 3 and not forced.stale
    record = store.get_fetch("sec-company-directory")
    assert record is not None and record.provider == "SEC EDGAR" and record.last_error is None


def test_failed_refresh_serves_the_old_copy_marked_stale(sec_setup):
    clock, sec, store, client = sec_setup
    payload, first = client.company_facts(COST_CIK)
    assert payload["cik"] == COST_CIK

    clock.advance(days=2)
    sec.failure = httpx.Response(503)
    payload, stale = client.company_facts(COST_CIK)
    assert payload == costco_facts()
    assert stale.stale and stale.retrieved_at == first.retrieved_at
    assert "HTTP 503" in (stale.error or "")
    record = store.get_fetch(f"sec-companyfacts-{COST_CIK:010d}")
    assert record is not None and record.last_error_at == clock.now

    # While it is down the SEC is not asked again for a minute.
    attempts = sum(sec.calls.values())
    assert client.company_facts(COST_CIK)[1].error == stale.error
    assert sum(sec.calls.values()) == attempts

    # Garbage instead of JSON is treated the same way as an outage.
    clock.advance(seconds=61)
    sec.failure = httpx.Response(200, content=b"<html>maintenance</html>")
    assert client.company_facts(COST_CIK)[1].stale
    assert sum(sec.calls.values()) == attempts + 1


def test_first_fetch_failure_raises_instead_of_inventing_data(sec_setup):
    _clock, sec, _store, client = sec_setup

    with pytest.raises(DataUnavailableError, match="no XBRL"):
        client.company_facts(42)
    with pytest.raises(DataUnavailableError, match="no filing record"):
        client.submissions(42)

    sec.failure = httpx.Response(500)
    with pytest.raises(UpstreamError):
        client.submissions(COST_CIK)
    sec.failure = httpx.Response(200, content=b"not json")
    with pytest.raises(UpstreamError, match="unreadable"):
        client.submissions(COST_CIK)
    sec.failure = httpx.Response(200, content=b"[1, 2]")
    with pytest.raises(UpstreamError, match="unexpected"):
        client.company_facts(COST_CIK)
    # Nothing unusable was written to the cache along the way.
    sec.failure = None
    assert client.company_facts(COST_CIK)[0] == costco_facts()


def test_company_directory_parsing_is_defensive():
    payload = directory_payload()
    payload["data"] += [
        [COST_CIK, "Duplicate", "COST", "NYSE"], ["bad", "Row", "X"], [5, "No T", ""],
    ]
    companies = parse_company_directory(payload)
    assert [company.ticker for company in companies] == ["COST", "CSTT", "EXM-B", "IFRS", "ORGN"]
    assert companies[0] == Company("COST", COST_CIK, "COSTCO WHOLESALE CORP /NEW", "Nasdaq")
    assert companies[-1].exchange is None

    without_fields = {"data": [[1, "Alpha Inc", "alp", "NYSE"]]}
    assert parse_company_directory(without_fields)[0].ticker == "ALP"
    for broken in ([], {"data": "x"}, {"fields": ["cik"], "data": [[1]]}, {"data": []}):
        with pytest.raises(UpstreamError):
            parse_company_directory(broken)


def test_filing_links_point_at_the_sec_index_page():
    assert filing_index_url(COST_CIK, "0000909832-26-000093") == (
        "https://www.sec.gov/Archives/edgar/data/909832/000090983226000093/"
        "0000909832-26-000093-index.htm"
    )
    assert filing_index_url(COST_CIK, "") is None
    assert filing_index_url(COST_CIK, "not-an-accession") is None


def test_store_search_ranks_ticker_matches_first(tmp_path: Path):
    store = TerminalStore(f"sqlite:///{tmp_path / 'terminal.sqlite3'}")
    store.replace_companies(parse_company_directory(directory_payload()))

    assert store.company_count() == 5
    assert [c.ticker for c in store.search_companies("cost")] == ["COST", "CSTT"]
    assert [c.ticker for c in store.search_companies("C")][:2] == ["COST", "CSTT"]
    assert len(store.search_companies("C")) == 5
    assert [c.ticker for c in store.search_companies("class b")] == ["EXM-B"]
    assert [c.ticker for c in store.search_companies("co", limit=1)] == ["COST"]
    # LIKE wildcards in user input are matched literally.
    assert [c.ticker for c in store.search_companies("100%")] == ["ORGN"]
    assert [c.ticker for c in store.search_companies("organic_")] == ["ORGN"]
    assert store.search_companies("%") == [c for c in store.search_companies("100%")]
    assert store.search_companies("_x_") == []
    assert store.search_companies("   ") == []
    assert store.get_company("cost") == parse_company_directory(directory_payload())[0]
    assert store.get_company("NOPE") is None

    store.replace_companies([Company("ONLY", 1, "Only One")])
    assert store.company_count() == 1
    store.close()


def test_store_round_trips_facts_and_ingestion_state(tmp_path: Path):
    store = TerminalStore(f"sqlite:///{tmp_path / 'terminal.sqlite3'}")
    facts = normalize_company_facts(costco_facts())
    fetched_at = dt.datetime(2026, 11, 17, 12, 30, 15, 123456, tzinfo=dt.timezone.utc)

    assert store.get_ingestion(COST_CIK) is None
    store.replace_facts(COST_CIK, facts, source_fetched_at=fetched_at, definitions_hash="abc")
    store.replace_facts(COST_CIK, facts, source_fetched_at=fetched_at, definitions_hash="abc")

    loaded = store.get_facts(COST_CIK)
    assert sorted(loaded, key=repr) == sorted(facts, key=repr)
    ingestion = store.get_ingestion(COST_CIK)
    assert ingestion is not None
    assert ingestion.source_fetched_at == fetched_at
    assert (ingestion.definitions_hash, ingestion.fact_count) == ("abc", len(facts))

    annual = store.get_facts(COST_CIK, metrics=["net_income"], period_type="annual")
    assert [fact.period_key for fact in annual] == ["FY2025", "FY2026"]
    derived = [fact for fact in loaded if fact.derived]
    assert derived and json.dumps(derived[0].components)
    assert store.get_facts(1) == []
    assert store.get_fetch("missing") is None
    store.record_fetch_error("missing", "ignored", fetched_at)
    store.close()
