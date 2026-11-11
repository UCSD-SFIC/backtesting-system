# Backtesting System

A local web dashboard for testing historical investment ideas and preparing
paper portfolio recommendations. The browser is the main interface; Python
runs the simulations behind it. The app does not connect to a brokerage or
place orders.

## Start the dashboard

Install Python 3.10 or newer and Node.js/npm, then run these commands from the
repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./scripts/start-dashboard.sh
```

Open <http://127.0.0.1:8000>. The start script installs frontend packages on
first use, builds the dashboard, and starts the local API. Leave the terminal
running while you use the app. Press `Ctrl+C` to stop it.

Market history comes from `yfinance` by default and requires an internet
connection. Polygon is optional: install `polygon-api-client` in the virtual
environment and set `POLYGON_API_KEY` before selecting it in the dashboard.

## Use the dashboard

### Backtests

1. Choose a strategy template. The included examples are fixed-weight
   portfolios, a simple moving-average crossover, and an exponential
   moving-average example.
2. Set the date range, ticker symbols, data source, and simulated trading
   cost. For the fixed-weight template, set each asset's target percentage
   and choose a rebalance schedule.
3. Select **Run backtest**. The app saves the configuration, price history,
   simulated results, metrics, and target holdings when available.
4. Select a saved run to inspect its growth chart and metrics. You can mark
   a run as draft, reviewed, or superseded.

Open **Guide & TOML** in the dashboard for a walkthrough of the full flow and
an annotated template example. The default templates are examples, not
recommendations. A backtest uses historical data and can be affected by data
gaps, corporate actions, and the assumptions in its configuration.

### How the TOML templates work

Files in `configs/` are starting settings for a run. TOML uses `key = value`
lines and named sections in square brackets. For example:

```toml
tickers = ["SPY", "BND"]
start = 2024-01-01
end = 2024-12-31

[strategy]
name = "fixed_weight"

[strategy.params]
weights = { SPY = 0.5, BND = 0.5 }
rebalance = "monthly"

[data]
provider = "yfinance"
```

`tickers` names the assets to fetch. `start` and `end` set the test period.
`strategy.name` selects the Python strategy; its `params` supply that
strategy's settings. Weight values are fractions, so `0.5` is 50% and all
weights together must equal `1.0`. `data.provider` selects the price source.
The optional `[execution] cost_bps` sets simulated turnover cost; one basis
point is 0.01%.

The dashboard loads a TOML template and lets you edit common run settings,
including dates, assets, data source, cost, portfolio weights, and indicator
windows. The price interval, benchmark, and risk-free rate still come from
the template; edit the TOML file to change those values. Changing a dashboard
field affects the next run and its saved configuration; it does
**not** change the TOML file. You can also edit a template in `configs/`
directly to change its starting values. SMA and EMA indicator windows are
editable in the dashboard. To add a new strategy type, see the customization
section below.

### Scenarios

Enter ticker weights for two candidate portfolios and assumed one-period
price changes for each asset. **Calculate sensitivity** shows the contribution
of each asset and the total response of each portfolio. These shocks are
user-supplied assumptions, not forecasts.

To compare the same portfolios against historical prices, first select a
saved backtest and choose **Compare historical returns**. This comparison
resets weights each bar and excludes trading costs; the regular backtest uses
its configured rebalance schedule and simulated costs.

### Paper rebalance

Select a saved fixed-weight run to load its target weights and latest prices.
Enter current whole-share holdings and available cash, or import a CSV with
`ticker,shares` columns. **Calculate paper rebalance** shows proposed share
changes, estimated costs, and leftover cash. Download the CSV for review.
The output is a simulation; it is not sent to a broker.

## Customize a strategy

The browser lets you change the settings exposed by a template. To add a new
strategy type, implement the `Alpha` interface in `strategy/`, register it in
`strategy/registry.py`, and create a TOML template in `configs/`. The engine
uses the same data and result interfaces for every registered strategy.

The CLI is available for scripts and repeatable research:

```bash
python -m pipeline.cli run --config configs/fixed_weight.toml --no-plot --save-run runs
python -m pipeline.cli validate-data --config configs/sma_crossover.toml
python -m pipeline.cli compare-runs --run-dir runs
```

Run `python -m pipeline.cli --help` for paper-rebalance and scenario-analysis
options. If the virtual environment is not activated, use `.venv/bin/python`
in place of `python`.

## Data, storage, and architecture

- `data/` fetches, validates, and caches normalized market history as Parquet.
- `strategy/` contains the common `Alpha` interface and public example strategies.
- `engine/` applies target weights, schedule changes, and simulated costs.
- `analytics/` calculates return and risk metrics.
- `research/` supports portfolio comparisons and scenario tables.
- `paper/` calculates whole-share paper recommendations.
- `experiments/` stores local run artifacts and review states.
- `web/` provides the local FastAPI backend; `frontend/` contains the browser UI.

Saved runs go in `runs/`; price history is cached in `history_cache/`. Both
folders are ignored by Git. Set `BACKTEST_DATABASE_URL` to a SQLAlchemy
SQLite or PostgreSQL URL if you also want a searchable run metadata catalog.
For PostgreSQL, install the optional `psycopg` dependency.

## Development checks

```bash
.venv/bin/ruff check .
.venv/bin/pyright
.venv/bin/python -m pytest --cov --cov-fail-under=80
npm test --prefix frontend
npm run build --prefix frontend
```

GitHub Actions runs these checks on pull requests. The standalone roadmap is
in [ROADMAP.md](ROADMAP.md).
