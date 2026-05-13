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

Run the dual-momentum strategy:

```bash
python -m pipeline.run_trend_regime
```

Run the WEDNESDAY+ strategy:

```bash
python -m pipeline.run_wednesday_plus
```
