# Backtesting System Roadmap

## Product direction

Build a browser-first research tool for historical backtests, portfolio
comparisons, scenario analysis, and paper rebalance recommendations. The
application remains local and does not place brokerage orders.

## Current release

- A React and TypeScript dashboard starts and reviews backtests through a
  FastAPI backend.
- Users can run public example strategies, including fixed target weights
  and simple moving-average indicators.
- The Python engine supports reusable data-provider and strategy interfaces,
  validated configuration, simulated costs, and performance metrics.
- Runs can be saved and reviewed. The dashboard compares historical portfolio
  combinations, calculates user-defined scenario sensitivity, and exports
  paper rebalance CSVs.
- Tests, type checks, linting, coverage, and frontend builds run in CI.

## Next improvements

| Area | Work | Why it matters |
| --- | --- | --- |
| Strategy setup | Let users save and duplicate their own browser configurations | Makes repeat research easier without editing TOML. |
| Portfolio research | Add reusable scenario presets and clearer comparison charts | Makes assumptions easier to inspect and discuss. |
| Data quality | Show coverage and missing-price warnings before a run | Helps users judge whether a result is dependable. |
| Experiments | Add search and filters for saved runs | Keeps a growing research library manageable. |
| Reporting | Export a readable run summary with settings, metrics, and assumptions | Makes review and sharing simpler. |
| Reliability | Add browser end-to-end tests for the key workflows | Catches integration regressions. |

## Four-contributor split

| Contributor | Ownership | Main technologies |
| --- | --- | --- |
| 1 | Market-data providers, validation, cache, and data-quality display | Python, Polars, Parquet, pytest |
| 2 | Public strategy interfaces, example strategies, and engine correctness | Python, NumPy, pytest |
| 3 | Portfolio comparisons, scenarios, paper calculations, and saved runs | Python, FastAPI, SQLAlchemy, pytest |
| 4 | Dashboard configuration, charts, exports, and browser tests | TypeScript, React, Vite, Playwright |

Contributors can work in parallel against the tested API and saved-run
schemas. Changes to those shared formats should be agreed on before merging.

## Release standard

A new feature is complete when a user can perform it from the browser, its
inputs and outputs are clear, automated tests cover its important rules, and
the run stores enough settings to understand the result later.
