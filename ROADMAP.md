# Backtesting System Roadmap

## What this project is

A tool for testing investing ideas and paper portfolios. It can simulate a
strategy, compare portfolio combinations and market-risk scenarios, identify
potential hedges, and create a **paper rebalance recommendation**.

It will **never** place live brokerage orders, hold funds, or manage real-money
accounts. A person may use its output to make a separate decision, but the app
itself stays a research and paper-trading tool.

## Where we are now

**Stage: allocation backtester with paper and scenario research in progress.**

- The project can fetch data from yfinance or Polygon.
- It has an engine, strategy interface, EMA/SMA examples, metrics, charts, and
  automated tests and CI.
- It can rank a large stock universe, combine strategy sleeves, and model
  scheduled rebalances with simulated costs.
- Paper rebalance, scenario research, saved runs, and a local browser interface
  have initial implementations; their integration and validation are underway.

| Original task | Status |
| --- | --- |
| 1. Architecture layers | Complete |
| 2. yfinance pipeline | Complete; shared caching and validation added |
| 3. Testing, CI, and profiling | Complete for the current engine; extend checks as features grow |
| 4. Backtest metrics | Complete |

## Phase 1: Make the foundation reliable

Finish the existing work before adding a UI.

- Complete yfinance caching, normalized price data, and data validation.
- Add GitHub Actions so tests run automatically on every pull request.
- Add coverage, linting, type checking, and a small performance benchmark.
- Add a simple validated configuration file instead of editing script values.

**Done when:** anyone can clone the project, configure a run, and get the same
tested result on their computer.

## Phase 2: Build the allocation backtester

Support the reference quant-allocation strategy.

- Load an eligible stock universe and rank it at each rebalance date.
- Add traditional momentum and 52-week-high signals.
- Combine strategy sleeves, such as 70% momentum and 30% 52-week-high.
- Select the top N stocks, apply equal/capped weights, and rebalance monthly or
  quarterly.
- Track realistic simulated costs, turnover, cash, and drawdown.

**Done when:** the project can reproduce the allocation-style research from the
existing notebooks using tested application code rather than notebook cells.

## Phase 3: Add paper rebalancing and reproducible experiments

Turn a backtest result into a useful paper-portfolio workflow.

- Save each run's settings, data version, metrics, holdings, and results.
- Compare parameter choices and run walk-forward tests to reduce overfitting.
- Model scenarios and produce sensitivity tables for individual assets and
  portfolio combinations.
- Compare candidate portfolio combinations by return, drawdown, correlation,
  concentration, and scenario behavior to support research into assets that
  may move differently from the market and potentially hedge market risk.
- Import a paper portfolio or prior recommendation from CSV.
- Convert target weights into paper target shares and buy/sell deltas.
- Export a paper rebalance packet: target holdings, simulated trades, turnover,
  estimated costs, and leftover cash.

**Done when:** a user can run a monthly paper rebalance, review the output, and
compare it with past simulated runs, scenarios, and candidate portfolio
combinations. No broker connection is involved.

## Phase 4: Make it easy to use

Build a small app around the proven engine.

- Add CLI commands: `run`, `compare-runs`, `paper-rebalance`, and
  `validate-data`.
- Add an API and web dashboard for configuration, charts, saved runs, scenario
  sensitivity tables, portfolio comparisons, and downloadable paper-rebalance
  packets.
- Add simple review states such as draft, reviewed, and superseded.

**Done when:** a non-programmer can use a browser to run and inspect a paper
backtest without writing Python.

## Technology plan

Use only the next layer when the project needs it.

| When | Use | Purpose |
| --- | --- | --- |
| Now | Python, Polars, pytest | Backtesting math, data processing, and tests |
| Phase 1 | Pydantic, GitHub Actions, Ruff, Pyright | Safer configuration and automatic quality checks |
| Phase 3 | Parquet, PostgreSQL, Polars/NumPy | Save results and model scenarios, sensitivities, and portfolio comparisons |
| Phase 4 | FastAPI, TypeScript, React | Backend API and browser dashboard |
| Later only if needed | Docker, OpenTelemetry, background job queue | Easier deployment, debugging, and long-running jobs |

## Work split for four contributors

| Contributor | Owns | Technologies | Starts in | Primary handoff |
| --- | --- | --- | --- | --- |
| 1 - data and reliability | Providers, cache, normalized data schema, data validation, configuration, CI, linting, and benchmarks | Python, yfinance, Polars, Parquet, Pydantic, pytest, GitHub Actions, Ruff, Pyright | Phase 1 | Provides validated market-history data and run configuration. |
| 2 - strategy and research | Universe ranking, momentum/52-week-high signals, multi-sleeve weights, rebalance schedules, walk-forward tests, market relationships, and scenario calculations | Python, Polars, NumPy, pytest | Phase 2 | Produces target weights, hedge research, and scenario results from validated history. |
| 3 - paper portfolio engine | Simulated costs, cash, target shares, holdings CSV import, trade ledger, and rebalance packet exports | Python, Polars, Pydantic, CSV/Parquet, pytest | Phase 2 | Converts weights into paper holdings and reviewed buy/sell recommendations. |
| 4 - AM research and experiments | Scenario models, sensitivity tables, portfolio-combination analysis, saved research artifacts, and CLI reports | Python, Polars, NumPy, PostgreSQL, SQLAlchemy, pytest | Phase 3 | Produces reviewable hedge and portfolio-comparison research artifacts. |

Recommended sequence:

1. Contributor 1 completes the Phase 1 foundation.
2. Contributors 2 and 3 work in parallel using stable fixture data.
3. Contributor 4 builds scenario research and saved experiment artifacts in
   parallel with Contributors 2 and 3.
4. Start the web app only after those artifact formats are stable; split that
   work into frontend, API, and end-to-end testing tasks rather than assigning
   it to one contributor.

## Concurrent team kickoff brief

### Goal

Turn this repository from a local research prototype into a repeatable
backtesting and **paper-rebalancing** tool. A user should eventually be able to
choose a universe and strategy settings, run a backtest, inspect results, and
download a paper recommendation for target shares and buy/sell deltas.

### How we will work

All four contributors can start now. Each person should use a separate feature
branch and pull request. Do not edit another contributor's owned area without
agreeing first. Use small, focused pull requests and add tests for every new
rule.

The first shared task is to agree on these formats. Until the real versions are
ready, contributors may use fixture CSV or Parquet files matching them.

```text
Normalized price history
date, ticker, open, high, low, close, adjusted_close, volume

Strategy output
date, ticker, target_weight

Paper-rebalance input
current holdings CSV + target weights + available cash

Paper-rebalance output
target shares, buy/sell deltas, estimated costs, leftover cash

Saved run
run ID, configuration, data version, metrics, holdings, trades, result files
```

### Contributor 1 — Data and reliability

**Owns:** data providers, caching, normalized market-data schema, validation,
configuration, CI, linting, and benchmarks.

**First deliverables:**

- Define and test the normalized price-history schema.
- Finish the yfinance cache and data-quality checks.
- Add a validated configuration file for selecting provider, dates, universe,
  benchmark, and strategy settings.
- Add GitHub Actions to run tests, linting, and type checks on pull requests.

**Handoff:** a validated price-history dataset and run configuration that the
engine and strategies can trust.

### Contributor 2 — Strategy and research

**Owns:** universe ranking, signals, weights, rebalance schedules, and
research-validity tests.

**First deliverables:**

- Implement traditional momentum and 52-week-high signals from fixture data.
- Rank an eligible universe and select the top N stocks at each rebalance.
- Combine sleeves, initially with a configurable 70/30 split.
- Add monthly and quarterly rebalance schedules.
- Add tests that rule out accidental look-ahead bias.
- Calculate market relationships and scenario/sensitivity results for assets
  and candidate portfolio combinations.

**Handoff:** dated target weights, backtest research results, and scenario
artifacts that show potential diversification or hedge behavior.

### Contributor 3 — Paper portfolio engine

**Owns:** portfolio accounting, cash, target shares, holdings import, paper
trade ledger, and rebalance packet exports.

**First deliverables:**

- Accept target weights, current paper holdings, and available cash.
- Calculate whole-share target positions and buy/sell deltas.
- Track estimated trading costs, turnover, and leftover cash.
- Import holdings from CSV and export a paper-rebalance CSV/report.
- Add deterministic tests for rounding, cash limits, and trade calculations.

**Handoff:** a reviewable paper rebalance packet; it is a recommendation, not
an order-execution system.

### Contributor 4 — AM research and experiments

**Owns:** scenario models, sensitivity tables, portfolio-combination analysis,
saved research artifacts, and CLI reports.

**First deliverables:**

- Define standard market and custom scenarios, then calculate asset and
  portfolio sensitivity tables from fixture data.
- Compare candidate portfolio combinations by return, drawdown, correlation,
  concentration, and scenario behavior.
- Design the saved-run record and store scenarios, sensitivity results, and
  portfolio-comparison artifacts with each run.
- Create CLI commands for `run`, `compare-runs`, `paper-rebalance`, and
  `validate-data` using mock artifacts at first.

**Handoff:** saved, reviewable research artifacts that can later be shown in
the web app.

### Integration order

1. Merge the shared schemas, fixture data, and configuration decisions first.
2. Merge Contributor 1's reliable data pipeline.
3. Merge Contributors 2 and 3 independently, then test their connection:
   target weights in, paper rebalance packet out.
4. Merge Contributor 4's scenario and saved-run artifacts against the same
   stable inputs and outputs.
5. Once the core artifacts are stable, split Phase 4 web work among the team:
   frontend screens, API endpoints, and end-to-end tests are separate tasks.

### Definition of a successful first release

A user can choose settings, run a tested strategy on historical data, inspect
performance and holdings, model scenarios, use sensitivity tables to compare
portfolio combinations and potential market hedges, import a paper portfolio,
and download a paper rebalance recommendation. The tool does not submit
brokerage orders.
