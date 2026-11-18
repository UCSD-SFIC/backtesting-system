# Research Terminal data backend

This is the Developer 1 (data and backend) piece of Phase 1 of the SFIC
Research Terminal roadmap. It gives the rest of the team one place to get:

- company and ticker search
- a company overview (profile, last price, market cap, latest annual figures)
- daily price history
- income statement, balance sheet and cash flow, annual and quarterly
- the source and refresh time behind every number

It lives in the `terminal/` package and is served by the existing FastAPI app
in `web/app.py`. Nothing here uses AI, and nothing is ever filled in with
sample data: if a value is not available you get `null` and a reason.

## Setup

The SEC requires every client to identify itself with a name and contact
email. Copy `.env.example` to `.env` and set your own:

```bash
cp .env.example .env
# then edit .env:
SEC_USER_AGENT="SFIC Research Terminal yourname@ucsd.edu"
```

Install and start the app the usual way (`./scripts/start-dashboard.sh`), then
try <http://127.0.0.1:8000/api/companies?q=costco>.

To check that live data loads on your machine without the browser:

```bash
.venv/bin/python -m terminal COST AAPL
```

It prints the last close, market cap, a few annual figures with their filing,
and when each source was fetched.

| Setting | Default | What it does |
| --- | --- | --- |
| `SEC_USER_AGENT` | none, required | Name and email sent to the SEC |
| `TERMINAL_DATA_DIR` | `terminal_data` | Database, raw SEC payloads, price files (ignored by Git) |
| `TERMINAL_DATABASE_URL` | SQLite file in the data dir | Any SQLAlchemy URL |
| `TERMINAL_PRICE_PROVIDER` | `yfinance` | `yfinance` or `polygon` (needs `POLYGON_API_KEY`) |

## API conventions

Every successful response has the same two keys:

```json
{
  "data": { },
  "meta": {
    "generated_at": "2026-11-17T20:00:00+00:00",
    "sources": [
      {
        "id": "sec-companyfacts-0000909832",
        "provider": "SEC EDGAR",
        "url": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000909832.json",
        "retrieved_at": "2026-11-17T19:58:11+00:00",
        "stale": false,
        "error": null,
        "note": null
      }
    ],
    "warnings": []
  }
}
```

- `meta.sources` lists every source behind the response and when it was last
  fetched. `stale: true` means the last refresh failed and you are looking at
  the previous copy; `error` says why and a `stale_source` warning is added.
- `meta.warnings` is a list of `{code, message}`. The overview uses it when
  one section could not load (`profile_unavailable`, `price_unavailable`,
  `financials_unavailable`) so the page can still show the rest.

Errors always look like this, with a matching HTTP status:

```json
{ "detail": "NOPE was not found in the SEC company directory...", "code": "unknown_ticker" }
```

| Status | `code` | Meaning |
| --- | --- | --- |
| 404 | `unknown_ticker` | Not in the SEC company directory |
| 404 | `data_unavailable` | Company exists but the source has nothing for this request |
| 422 | (FastAPI validation) | Bad query parameter |
| 502 | `upstream_error` | Source failed and there is no cached copy |
| 503 | `rate_limited` | Source is throttling; see the `Retry-After` header |
| 503 | `not_configured` | `SEC_USER_AGENT` is missing |

### Values and provenance

Every financial value is a cell:

```json
{
  "period": "FY2026",
  "value": 9226000000.0,
  "unit": "USD",
  "derived": false,
  "formula": null,
  "source": {
    "provider": "SEC EDGAR",
    "source_id": "sec-companyfacts-0000909832",
    "concept": "us-gaap:NetIncomeLoss",
    "accession": "0000909832-26-000093",
    "form": "10-K",
    "filed": "2026-10-07",
    "period_start": "2025-09-01",
    "period_end": "2026-08-30",
    "url": "https://www.sec.gov/Archives/edgar/data/909832/000090983226000093/0000909832-26-000093-index.htm"
  },
  "components": []
}
```

`source.url` opens the filing on sec.gov, which is what a provenance hover
should link to. A derived value has `derived: true`, a `formula` such as
`"FY2026 - YTD Q3 FY2026"`, and `components` listing each input with its own
filing. A missing value is:

```json
{ "period": "FY2026-Q4", "value": null, "unit": "USD/shares", "missing_reason": "not_derivable" }
```

`missing_reason` is `not_reported` (the company did not tag it for that
period) or `not_derivable` (for example Q4 EPS, which is not full-year EPS
minus nine-month EPS). A cell has either `source` or `missing_reason`, never
both and never neither.

## Endpoints

### `GET /api/companies?q=<text>&limit=10`

Search by ticker or company name. Exact ticker first, then ticker prefix, then
name matches. `limit` is 1 to 50.

`data`: `{ "query", "results": [{ "ticker", "cik", "name", "exchange" }] }`

### `GET /api/companies/{ticker}`

Company overview. `BRK.B` and `BRK-B` both work.

`data`:

- `company`: ticker, cik, name, exchange, sic, sic_description,
  fiscal_year_end (`MM-DD`), state_of_incorporation, website, entity_type,
  edgar_url
- `price`: last_close, last_close_date, previous_close, change,
  change_percent, week_52_high, week_52_low, source_id, retrieved_at
  (or `null`)
- `market_cap`: a derived cell, `last_close * shares_outstanding`, with both
  inputs and the date of the share count in `components`
- `latest_annual`: `{ period, fiscal_year, period_end, metrics: { key: cell } }`
  for revenue, operating_income, net_income, eps_diluted, operating_cash_flow,
  capital_expenditures, cash_and_equivalents, long_term_debt, total_assets,
  total_equity

### `GET /api/companies/{ticker}/prices?range=1y`

Daily bars. `range` is one of `1m 3m 6m 1y 3y 5y max` (max is about 10 years).

`data`: `{ ticker, interval: "day", range, currency, snapshot, bars: [{ date, open, high, low, close, volume }] }`

### `GET /api/companies/{ticker}/financials?statement=income&period=annual&limit=5`

- `statement`: `income`, `balance`, `cash_flow`
- `period`: `annual` or `quarterly`
- `limit`: number of periods, newest first (default 5 annual, 8 quarterly, max 40)

`data`:

```json
{
  "ticker": "COST", "cik": 909832, "statement": "income", "period": "quarterly",
  "currency": "USD",
  "periods": [
    { "key": "FY2026-Q4", "fiscal_year": 2026, "fiscal_quarter": 4,
      "period_start": "2026-05-11", "period_end": "2026-08-30" }
  ],
  "rows": [
    { "metric": "net_income", "label": "Net income", "unit": "USD", "kind": "flow",
      "values": [ { "period": "FY2026-Q4", "value": 2998000000.0, "derived": true, "...": "..." } ] }
  ]
}
```

`rows[i].values[j]` lines up with `periods[j]`, so the table can be rendered
directly.

### `GET /api/financial-metrics`

The metric definitions: key, label, statement, unit, and the XBRL concepts
each one is read from, in priority order.

## How the numbers are built

Source: the SEC's XBRL "company facts" API, which is the tagged data from
each company's own 10-K and 10-Q filings.

- **Fiscal periods come from dates, not from the SEC's `fy`/`fp` fields.**
  Those fields describe the filing a value appeared in, so a FY2026 10-K
  labels its FY2025 comparatives as `fy=2026`. Fiscal year ends are detected
  from the 12-month periods in annual filings. The latest year takes its
  label from its own 10-K and earlier years count back from it.
- **Quarters are placed by where they end in the fiscal year**, so companies
  with uneven quarters (Costco is 12/12/12/16 weeks) land correctly.
- **Discrete quarters are derived when only year-to-date is reported.** Cash
  flow in a 10-Q is always year-to-date, and Q4 is never reported on its own.
  Q2 = 6M - Q1, Q3 = 9M - 6M, Q4 = FY - 9M. These cells are marked `derived`
  with the formula and both inputs.
- **Per-share figures and weighted share counts are never differenced.**
  Their Q4 is `not_derivable` unless the company reports it.
- **When a period is reported in more than one filing, the most recently
  filed value is used.** That means restated numbers win, and the source
  points at the later filing. Showing "as originally reported" is not done yet.
- **Each metric tries a list of XBRL concepts in order** (see
  `terminal/metrics.py`), per period, because companies change tags over
  time. The cell's `source.concept` says which one was used.
- **Only reported values are stored.** Gross profit is empty for a company
  that does not report a gross profit line. Margins, FCF, EBITDA, EV, TTM and
  growth rates are analysis-layer calculations to build on top of this.

Prices come from the existing `data` providers (yfinance by default). Closes
are adjusted for splits but not dividends. Market cap uses the latest share
count the company reported on a filing cover page, with its date shown.

## Refresh and storage

| Data | Refreshed after | Stored in |
| --- | --- | --- |
| SEC company directory | 1 day | `terminal_data/raw/` and the `terminal_companies` table |
| SEC company facts | 12 hours | `terminal_data/raw/` and `terminal_financial_facts` |
| SEC submissions (profile, filing list) | 1 hour | `terminal_data/raw/` |
| Daily prices | 30 minutes | `terminal_data/prices/<provider>/` (Parquet) |

`terminal_source_fetches` records the last successful fetch and last error
for every source. All SEC requests share one rate limiter (5 per second, the
SEC allows 10) and are tried up to three times on 429 and 5xx responses,
honouring `Retry-After`. If a refresh fails and an older copy exists, the older copy is
served and marked stale, and the source is not asked again for 60 seconds.

Stored facts are rebuilt automatically when the source is re-fetched or when
the metric definitions change.

## Using it from other workstreams

Please do not add a second SEC or price fetcher. Reuse these:

**Filings (Developer 2).** `TerminalService().sec` is a shared SEC client.
`sec.submissions(cik)` returns the full submissions JSON (the recent 10-K,
10-Q and 8-K list with accession numbers and primary documents) plus its
source info. `sec.get_json(source_id, url, ttl=...)` fetches any other SEC
JSON through the same cache and rate limiter. `terminal.sec.filing_index_url`
builds the sec.gov link for an accession number. `service.resolve(ticker)`
gives you the CIK.

**Analysis and valuation (Developer 3).** `service.facts_frame("COST")`
returns one Polars frame with every normalized metric for every fiscal
period: `metric, period_type, period, fiscal_year, fiscal_quarter,
period_start, period_end, value, unit, derived, formula, concept, accession,
form, filed`. Build growth, margins, TTM, scores and valuation on that. The
metric list in `terminal/metrics.py` is a first pass; add or reorder concepts
there and check them against real filings. `service.price_service.history(ticker)`
returns daily OHLCV in the shared `data.schema` format.

**Frontend (Developer 4).** Use the endpoints above. Show `meta.sources[].retrieved_at`
for "as of" labels, `stale` for a warning badge, and each cell's `source.url`
for the provenance hover. Handle `value: null` with `missing_reason` as an
empty state, and `meta.warnings` on the overview as per-section notices. For
tests, `tests/terminal_fixtures.py` has an offline harness with the same
response shapes.

## Known limits and open decisions

- **yfinance licensing.** yfinance is an unofficial Yahoo Finance client and
  is meant for personal and educational use. The team should confirm it is
  acceptable for SFIC or switch `TERMINAL_PRICE_PROVIDER` to Polygon.
- **US-GAAP filers only.** Foreign companies reporting under IFRS return
  `data_unavailable` for financials.
- **Banks and insurers** tag their statements differently, so several rows
  will be `not_reported` until the concept lists are extended.
- **Multi-class companies** (for example Alphabet) may have no usable cover
  page share count, so market cap can be missing or understated.
- **No segment data, analyst estimates, or news.** Segment facts are not in
  the company facts API, and estimates need a licensed source (roadmap
  Phase 2 and 3).
- **Fiscal-year changes.** Periods that fall in the gap of a changed fiscal
  year end are skipped rather than guessed.
- **Not verified against live SEC responses in CI.** Tests run offline on
  fixtures (the Costco net income figures in them are real SEC values). Run
  `python -m terminal COST AAPL` to check live data.
