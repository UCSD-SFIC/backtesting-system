from dotenv import load_dotenv
import os
from samplealpha import sampleAlpha
from backtest import (
    run_backtest,
    plot_backtest,
    summarize_backtest,
)
from data import PolygonDataProvider, YFinanceDataProvider


if __name__ == "__main__":
    load_dotenv()

    provider_name = os.getenv("DATA_PROVIDER", "yfinance").lower()
    if provider_name == "polygon":
        api_key = os.getenv("POLYGON_API_KEY")
        if api_key is None:
            raise ValueError("POLYGON_API_KEY is not set in environment variables")
        data_provider = PolygonDataProvider(api_key)
    elif provider_name == "yfinance":
        data_provider = YFinanceDataProvider()
    else:
        raise ValueError("DATA_PROVIDER must be one of: polygon, yfinance")

    tickers = ["SPY", "SH"]
    alpha = sampleAlpha("US", "day", tickers, "2024-01-01", "2024-12-06")

    backtest_result = run_backtest(
        data_provider=data_provider,
        alpha=alpha,
        timespan="day",
        from_time="2024-01-01",
        to_time="2024-12-06",
    )

    metrics = summarize_backtest(backtest_result)
    print(f"Total return: {metrics['total_return']:.02%}")
    print(f"Sharpe ratio: {metrics['sharpe_ratio']:.3f}")
    print(f"Sortino ratio: {metrics['sortino_ratio']:.3f}")
    print(f"Annualized volatility: {metrics['annualized_volatility']:.02%}")
    print(f"Max drawdown: {metrics['max_drawdown']:.02%}")

    plot_backtest(backtest_result, tickers)
