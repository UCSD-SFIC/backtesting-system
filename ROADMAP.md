# Backtesting System Roadmap

This roadmap reflects the repository as of October 27, 2026. The next focus is
making results trustworthy and repeatable before turning the project into a
web product.

| Task | Status | Outcome |
| --- | --- | --- |
| 1. Architecture layers | Complete | `DataProvider`, `Alpha`, and `BacktestEngine` separate data, strategy, and simulation concerns. |
| 2. yfinance pipeline | In progress | yfinance works and is selectable through `DATA_PROVIDER`; finish shared cache, input validation, and a proper CLI/config interface. |
| 3. Quality, CI, and profiling | Started | Existing pytest coverage covers core paths; add CI, coverage gates, benchmarks, linting, typing, and performance regression checks. |
| 4. Performance metrics | Complete | Return, risk, drawdown, distribution, alpha, and beta metrics are calculated and displayed. |

## Next priorities

### 5. Realistic execution and portfolio accounting — High priority

Make a backtest represent tradable results rather than frictionless target
weights.

- Add an execution model for commissions, spread/slippage, borrow costs, cash
  interest, lot rounding, and position/weight limits.
- Produce a trade ledger, portfolio ledger, turnover, exposure, and cost
  attribution columns.
- Prevent look-ahead bias by making signal time, order time, and fill time
  explicit.
- Add deterministic unit and integration tests for each accounting rule.

**Skills exercised:** quantitative systems design, domain modelling, property
testing, and performance-oriented Polars work.

### 6. Research validity: walk-forward testing and experiment tracking — High priority

Prevent overfitting and make every result reproducible.

- Implement train/validation/test date splits and rolling walk-forward runs.
- Add parameter grids and seeded, reproducible experiment runs.
- Save each run's configuration, provider/version metadata, metrics, and
  result parquet files in a versioned run artifact.
- Add comparison reports including benchmark, turnover, drawdown, and
  out-of-sample summaries.

**Skills exercised:** experiment design, reproducible data engineering,
configuration modelling, and analytical reporting.

### 7. Configuration, CLI, and provider hardening — High priority

Turn the sample scripts into a reliable application interface.

- Use validated config files and environment overrides for provider, universe,
  dates, benchmark, strategy parameters, and execution assumptions.
- Add commands for `run`, `validate-data`, `list-runs`, and `compare-runs`.
- Give every provider the same parquet-cache contract, normalized OHLCV schema,
  timezone policy, cache invalidation policy, retries, and actionable errors.
- Add data-quality checks for duplicate/missing bars, invalid prices, and
  corporate-action handling.

**Skills exercised:** Pydantic-style schema validation, CLI/API design,
packaging, caching, and resilient integrations.

### 8. API and interactive dashboard — Medium priority

Build a useful review experience only after the experiment artifacts are
stable.

- Expose runs, strategies, artifacts, and comparison results through a typed
  API with an OpenAPI contract.
- Build a TypeScript/React dashboard for launching configured runs and
  comparing equity curves, drawdowns, weights, trade ledgers, and metrics.
- Start with local/background execution; introduce a durable job queue only
  when concurrent runs require it.

**Skills exercised:** FastAPI/OpenAPI, TypeScript/React, API contracts, data
visualization, and full-stack testing.

### 9. Production engineering and observability — Medium priority

Make the system easy to run, diagnose, and contribute to.

- Add GitHub Actions for tests, coverage, linting, type checks, and dependency
  vulnerability checks.
- Containerize the API/worker stack and add a PostgreSQL-backed run catalog
  when artifacts outgrow local files.
- Instrument provider fetches and backtest phases with structured logs,
  duration metrics, and OpenTelemetry traces.
- Publish an architecture decision record and contributor onboarding guide.

**Skills exercised:** Docker, GitHub Actions, PostgreSQL, OpenTelemetry, CI/CD,
and secure dependency management.

## Parallel work plan for two new contributors

| Contributor | Owns | Can start now | Handoff boundary |
| --- | --- | --- | --- |
| A — simulation/research | Task 5, then Task 6 | Execution model, trade ledger, no-look-ahead tests | Consumes normalized history; emits immutable result and experiment artifacts. |
| B — platform/product | Finish Task 2, Task 3, then Task 7 | Shared provider cache/schema, validated config/CLI, CI/coverage/benchmarks | Owns provider and application interfaces; does not change portfolio-accounting semantics. |

Once both tracks emit stable run artifacts, both contributors can jointly plan
Task 8: A owns research-result semantics and B owns API/dashboard delivery.

## Technology choices

Use technologies because they reduce a concrete risk, not just because they
look current on a résumé. FastAPI, Docker, PostgreSQL, TypeScript/React,
GitHub Actions, and OpenTelemetry make a coherent modern stack around the
existing Python/Polars engine. The 2025 Stack Overflow survey reported major
growth in FastAPI and Docker usage, while GitHub reported that Python accounted
for nearly half of new AI projects by August 2025. OpenTelemetry provides a
vendor-neutral standard for Python traces and metrics. These choices are
therefore appropriate learning investments, but the execution model,
walk-forward validation, and tests remain the product-critical work.

Sources: [Stack Overflow 2025 technology survey](https://survey.stackoverflow.co/2025/technology), [GitHub Octoverse analysis](https://github.blog/news-insights/octoverse/what-the-fastest-growing-tools-reveal-about-how-software-is-being-built/), and [OpenTelemetry Python instrumentation documentation](https://opentelemetry.io/docs/languages/python/instrumentation/).
