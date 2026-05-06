# Python Backtesting

This script runs backtesting with `yfinance` as the default data source.
Polygon is also supported.

## Architecture

The project is split into modular layers:

- `data_layer`: market data abstractions and providers (`PolygonDataProvider`, `YFinanceDataProvider`)
- `strategy_layer`: strategy interfaces (`Alpha`) and strategy implementations
- `engine_layer`: backtest orchestration and portfolio simulation
- `analytics`: performance and risk metrics
- `visualization`: result plotting

`backtest.py` and `data.py` remain as compatibility facades.

## Provider Switching

Set `DATA_PROVIDER` in `.env`:

- `DATA_PROVIDER=yfinance` (default, requires `yfinance` package)
- `DATA_PROVIDER=polygon` (requires `POLYGON_API_KEY`)

## Metrics

Performance summary includes:

- Total Return
- Sharpe Ratio
- Sortino Ratio
- Annualized Volatility
- Maximum Drawdown

## Setup

Create a local environment with `uv`:

```bash
uv venv
source .venv/bin/activate
uv pip install -r requirements-dev.txt
```

For runtime-only installs, use `requirements.txt` instead.
