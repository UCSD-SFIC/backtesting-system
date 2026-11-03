from __future__ import annotations

from collections.abc import Callable
from typing import Any

from strategy.alpha import Alpha
from strategy.ema_alpha import ExponentialMovingAverageAlpha
from strategy.sample_alpha import SampleAlpha

# Maps the `strategy.name` used in config files to a strategy class. Every
# class takes (universe, resolution, tickers, start, end, **params).
STRATEGIES: dict[str, Callable[..., Alpha]] = {
    "sma_crossover": SampleAlpha,
    "ema_dip": ExponentialMovingAverageAlpha,
}


def build_strategy(
    name: str,
    tickers: list[str],
    timespan: str,
    start: str,
    end: str,
    params: dict[str, Any] | None = None,
    universe: str = "US",
) -> Alpha:
    if name not in STRATEGIES:
        raise ValueError(
            f"Unknown strategy {name!r}; choose one of: {', '.join(sorted(STRATEGIES))}"
        )
    try:
        return STRATEGIES[name](universe, timespan, tickers, start, end, **(params or {}))
    except TypeError as exc:
        raise ValueError(f"Invalid params for strategy {name!r}: {exc}") from exc
