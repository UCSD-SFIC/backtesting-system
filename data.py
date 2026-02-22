from __future__ import annotations

from abc import ABC, abstractmethod
import os

import polars as pl


class DataProvider(ABC):
	@abstractmethod
	def get_history(
		self,
		tickers: list[str],
		timespan: str,
		from_time: str,
		to_time: str,
	) -> dict[str, pl.DataFrame]:
		pass


class PolygonDataProvider(DataProvider):
	def __init__(self, api_key: str, cache_dir: str = "history_cache"):
		from polygon import RESTClient

		self._client = RESTClient(api_key)
		self._cache_dir = cache_dir

	def get_history(
		self,
		tickers: list[str],
		timespan: str,
		from_time: str,
		to_time: str,
	) -> dict[str, pl.DataFrame]:
		histories: dict[str, pl.DataFrame] = {}

		for ticker in tickers:
			path = os.path.join(
				self._cache_dir,
				f"{ticker}-{timespan}-{from_time}-{to_time}.parquet",
			)
			try:
				histories[ticker] = pl.read_parquet(path)
			except FileNotFoundError:
				print(f"Downloading {ticker} data")
				aggs = self._client.get_aggs(
					ticker=ticker,
					multiplier=1,
					timespan=timespan,
					from_=from_time,
					to=to_time,
				)
				df = pl.DataFrame(aggs)
				if not os.path.exists(self._cache_dir):
					os.makedirs(self._cache_dir)
				df.write_parquet(path)
				histories[ticker] = df

		return histories
