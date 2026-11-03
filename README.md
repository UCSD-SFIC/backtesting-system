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

## Setup

Create a local environment with `uv`:

```bash
uv venv
source .venv/bin/activate
uv pip install -r requirements-dev.txt
```

For runtime-only installs, use `requirements.txt` instead.

Run the sample alpha:

```bash
python -m pipeline.run_sample
```

Run the exponential moving average sample alpha:

```bash
python -m pipeline.run_ema_sample
```

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
