from __future__ import annotations

import datetime as dt
from abc import ABC, abstractmethod

import polars as pl


class Alpha(ABC):
    @abstractmethod
    def update(self, market_slice: pl.DataFrame) -> None:
        """
        Update internal state with the latest market data slice.
        """

    @abstractmethod
    def get_weights(self) -> list[float]:
        """
        Return current portfolio weights in ticker order.
        """

    @abstractmethod
    def get_tickers(self) -> list[str]:
        """
        Return ticker universe in a deterministic order.
        """

    def should_rebalance(self) -> bool:
        """
        Whether the weights from the latest update are a new rebalance.

        The default rebalances to the target weights on every bar. Strategies
        that trade on a schedule return False between rebalance dates so
        positions drift with prices instead of being reset each bar.
        """
        return True

    def warmup_period(self) -> dt.timedelta:
        """
        How much history before the start date the strategy needs for its
        signals. Runners fetch from `start - warmup_period()`.
        """
        return dt.timedelta(0)
