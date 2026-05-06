from __future__ import annotations

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
