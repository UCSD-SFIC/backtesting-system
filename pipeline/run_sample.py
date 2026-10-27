from dotenv import load_dotenv
import os

from data import PolygonDataProvider, YFinanceDataProvider
from pipeline import plot_backtest, run_backtest, summarize_backtest
from strategy import SampleAlpha


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
    alpha = SampleAlpha("US", "day", tickers, "2024-01-01", "2024-12-06")

    backtest_result = run_backtest(
        data_provider=data_provider,
        alpha=alpha,
        timespan="day",
        from_time="2024-01-01",
        to_time="2024-12-06",
    )

    metrics = summarize_backtest(backtest_result, benchmark_ticker=tickers[0])
    print(f"Total return: {metrics['total_return']:.02%}")
    print(f"Compounding annual return: {metrics['compounding_annual_return']:.02%}")
    print(f"Sharpe ratio: {metrics['sharpe_ratio']:.3f}")
    print(f"Sortino ratio: {metrics['sortino_ratio']:.3f}")
    print(f"Annualized volatility: {metrics['annualized_volatility']:.02%}")
    print(f"Annual variance: {metrics['annual_variance']:.4f}")
    print(f"Max drawdown: {metrics['max_drawdown']:.02%}")
    print(f"Win rate: {metrics['win_rate']:.02%}")
    print(f"Loss rate: {metrics['loss_rate']:.02%}")
    print(f"Average win: {metrics['average_win']:.02%}")
    print(f"Average loss: {metrics['average_loss']:.02%}")
    print(f"Profit-loss ratio: {metrics['profit_loss_ratio']:.2f}")
    print(f"Expectancy: {metrics['expectancy']:.02%}")
    print(f"Beta vs {tickers[0]}: {metrics['beta']:.3f}")
    print(f"Alpha vs {tickers[0]}: {metrics['alpha']:.02%}")

    plot_backtest(backtest_result, tickers)


if __name__ == "__main__":
    main()
