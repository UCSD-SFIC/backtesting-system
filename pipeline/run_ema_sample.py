from dotenv import load_dotenv
import os

from data import PolygonDataProvider, YFinanceDataProvider
from pipeline import plot_backtest, run_backtest, summarize_backtest
from strategy import ExponentialMovingAverageAlpha


def main() -> None:
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
    alpha = ExponentialMovingAverageAlpha(
        "US",
        "2hour",
        tickers,
        "2025-01-01",
        "2025-12-06",
        ema_window=50,
        regime_window=200,
    )

    backtest_result = run_backtest(
        data_provider=data_provider,
        alpha=alpha,
        timespan="2hour",
        from_time="2025-01-01",
        to_time="2025-12-06",
    )

    metrics = summarize_backtest(backtest_result, benchmark_ticker=tickers[0])
    print(f"Total return: {metrics['total_return']:.02%}")
    print(f"Compounding annual return: {metrics['compounding_annual_return']:.02%}")
    print(f"Sharpe ratio: {metrics['sharpe_ratio']:.3f}")
    print(f"Max drawdown: {metrics['max_drawdown']:.02%}")
    print(f"Alpha vs {tickers[0]}: {metrics['alpha']:.02%}")
    print(f"Beta vs {tickers[0]}: {metrics['beta']:.3f}")

    plot_backtest(backtest_result, tickers)


if __name__ == "__main__":
    main()
