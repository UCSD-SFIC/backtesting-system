# Python Backtesting

This script runs backtesting with `yfinance` as the default data source.
Polygon is also supported.

## Architecture

The project is split into modular layers:

- `data`: market data abstractions and providers (`PolygonDataProvider`, `YFinanceDataProvider`)
- `strategy`: strategy interfaces (`Alpha`) and strategy implementations
- `engine`: backtest orchestration and portfolio simulation
- `pipeline`: runnable backtest workflow entrypoints
- `analytics`: performance and risk metrics
- `visualization`: result plotting

## Provider Switching

Set `DATA_PROVIDER` in `.env`:

- `DATA_PROVIDER=yfinance` (default, requires `yfinance` package)
- `DATA_PROVIDER=polygon` (requires `POLYGON_API_KEY`)

Build providers with `data.create_data_provider(name)`. It wraps the raw
provider so every source behaves the same way:

- **Schema:** each ticker's frame has `timestamp` (UTC epoch ms, Int64) and
  `open`, `high`, `low`, `close`, `volume` (Float64), sorted by time. The
  `to_time` date is inclusive for every provider.
- **Validation:** fetched data is checked for missing columns, nulls, duplicate
  or unsorted bars, non-positive prices, and negative volume (errors, which
  raise `DataValidationError`), plus inconsistent OHLC, >50% single-bar moves,
  and missing daily/weekly/monthly bars (warnings, which are logged).
- **Cache:** validated data is written to
  `history_cache/<provider>/<ticker>-<timespan>-<from>-<to>.parquet`. Ranges
  that end today or later are not cached because they are still changing. Pass
  `refresh_cache=True` to refetch, or `cache_dir=None` to disable caching.

## Metrics

Performance summary includes:

- Total Return
- Compounding Annual Return
- Sharpe Ratio
- Sortino Ratio
- Annualized Volatility
- Annual Variance
- Maximum Drawdown
- Win Rate
- Loss Rate
- Average Win
- Average Loss
- Profit-Loss Ratio
- Expectancy
- Beta vs benchmark
- Alpha vs benchmark

For the current sample setup, beta and alpha are measured against the first ticker in the selected universe.

Annualized metrics (compounding annual return, Sharpe, Sortino, volatility,
variance, alpha) scale by bars per year, inferred from the bar timestamps:
252 for daily, 52 for weekly, 12 for monthly, and 252 x the typical bars per
trading day for intraday (1,008 for 2-hour yfinance bars, 1,764 for hourly).
Pass `periods_per_year` to `summarize_performance` to override it.

## Setup

Create a local environment with `uv`:

```bash
uv venv
source .venv/bin/activate
uv pip install -r requirements-dev.txt
```

For runtime-only installs, use `requirements.txt` instead.

## Running backtests

Runs are described by a TOML config in `configs/`. Fields are validated, so a
typo, unknown strategy, bad date range, or unknown parameter fails with a clear
error instead of being silently ignored.

```bash
python -m pipeline.cli run --config configs/sma_crossover.toml
python -m pipeline.cli run --config configs/ema_dip.toml --no-plot --save-plot ema.png
python -m pipeline.cli validate-data --config configs/sma_crossover.toml
```

`run` prints every metric and opens the plot. `validate-data` fetches the
configured data, prints each ticker's bar count and every quality issue, and
exits with code 1 if any errors are found.

Override config values without editing the file:

- CLI flags: `--provider`, `--tickers SPY,SH`, `--start`, `--end`, `--refresh-cache`
- Environment: `DATA_PROVIDER`, `BACKTEST_CACHE_DIR`

The order of precedence is CLI flag, then environment variable, then config
file. Strategies are registered by name in `strategy/registry.py`.

`python -m pipeline.run_sample` and `python -m pipeline.run_ema_sample` still
work; they run the two sample configs.

## Allocation backtests

`configs/allocation.toml` runs the momentum / 52-week-high allocation strategy
(`strategy/allocation_alpha.py`) on a stock universe:

```bash
python -m pipeline.cli run --config configs/allocation.toml
```

- **Universe:** `universe_file` points to a CSV with a `ticker` column (use it
  instead of `tickers`). `universes/us_large_cap_sample.csv` lists 50 current
  large caps, so it is survivorship-biased; use point-in-time constituents for
  real research. Stocks with missing history are skipped until they have
  enough data.
- **Signals** (`strategy/signals.py`): 12-1 month momentum (`lookback`,
  `skip`) and price relative to the 52-week high (`high_window`), both in bars.
  Stocks below `min_price` are not ranked.
- **Sleeves:** `sleeves = { momentum = 0.7, high_52_week = 0.3 }` splits capital.
  Each sleeve holds its top `top_n` names at equal weight; a stock in both
  sleeves gets both weights. `max_weight` caps any one stock and spreads the
  excess over the other holdings.
- **Schedule:** the first trade is on the first bar on or after `start`, then
  on the first bar of each month (`rebalance = "monthly"`) or quarter
  (`"quarterly"`). Positions drift with prices between rebalances. Signals use
  closes through the rebalance bar and trades fill from the next bar. History
  before `start` is fetched automatically to warm up the signals.
- **Costs:** `[execution] cost_bps` charges each rebalance's turnover (sum of
  |target - drifted weight|). The run reports rebalances, average and annual
  turnover, total simulated costs, average cash, and the latest target
  holdings.
- **Benchmark:** `benchmark` can be outside the universe; it is fetched for
  comparison and never held.

Any strategy can trade on a schedule by overriding `Alpha.should_rebalance()`
and can request warm-up history with `Alpha.warmup_period()`.

## Development checks

CI runs these on every pull request; run them locally before pushing:

```bash
ruff check .                                   # lint (add --fix for safe autofixes)
pyright                                        # type check
python -m pytest --cov --cov-fail-under=80     # tests with coverage gate
python -m benchmarks.bench_engine              # engine timings, 100 tickers x 5 years
```

`benchmarks.bench_engine` uses seeded synthetic data, so before/after timings
for an engine change are comparable on the same machine. Pass `--tickers` and
`--days` to try larger universes.
