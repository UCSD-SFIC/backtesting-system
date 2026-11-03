from __future__ import annotations

import os
from pathlib import Path

from data.cache import CachedDataProvider
from data.providers import (
    DataProvider,
    PolygonDataProvider,
    ValidatedDataProvider,
    YFinanceDataProvider,
)

PROVIDER_NAMES = ("yfinance", "polygon")


def create_raw_provider(name: str, polygon_api_key: str | None = None) -> DataProvider:
    """Build an unwrapped provider by name (no validation, no cache)."""
    name = name.lower()
    if name == "polygon":
        api_key = polygon_api_key or os.getenv("POLYGON_API_KEY")
        if not api_key:
            raise ValueError("POLYGON_API_KEY is not set in environment variables")
        return PolygonDataProvider(api_key)
    if name == "yfinance":
        return YFinanceDataProvider()
    raise ValueError(f"DATA_PROVIDER must be one of: {', '.join(PROVIDER_NAMES)}")


def create_data_provider(
    name: str = "yfinance",
    cache_dir: str | Path | None = "history_cache",
    refresh_cache: bool = False,
    validate: bool = True,
    polygon_api_key: str | None = None,
) -> DataProvider:
    """
    Build a provider by name, wrapped with validation and the shared cache.

    Validation runs before caching, so data that fails checks is never written.
    Pass `cache_dir=None` to disable caching.
    """
    provider = create_raw_provider(name, polygon_api_key)
    if validate:
        provider = ValidatedDataProvider(provider)
    if cache_dir is not None:
        provider = CachedDataProvider(provider, cache_dir, refresh=refresh_cache)
    return provider
