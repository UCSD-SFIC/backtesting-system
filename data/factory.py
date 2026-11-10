from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from data.cache import CachedDataProvider
from data.providers import (
    DataProvider,
    PolygonDataProvider,
    ValidatedDataProvider,
    YFinanceDataProvider,
)


PROVIDER_NAMES = ("yfinance", "polygon")


def create_data_provider(
    name: str = "yfinance",
    cache_dir: Optional[str | Path] = "history_cache",
    refresh_cache: bool = False,
    validate: bool = True,
    polygon_api_key: Optional[str] = None,
) -> DataProvider:
    """
    Build a provider by name, wrapped with validation and the shared cache.

    Validation runs before caching, so data that fails checks is never written.
    Pass `cache_dir=None` to disable caching.
    """
    name = name.lower()
    provider: DataProvider
    if name == "polygon":
        api_key = polygon_api_key or os.getenv("POLYGON_API_KEY")
        if not api_key:
            raise ValueError("POLYGON_API_KEY is not set in environment variables")
        provider = PolygonDataProvider(api_key)
    elif name == "yfinance":
        provider = YFinanceDataProvider()
    else:
        raise ValueError(f"DATA_PROVIDER must be one of: {', '.join(PROVIDER_NAMES)}")

    if validate:
        provider = ValidatedDataProvider(provider)
    if cache_dir is not None:
        provider = CachedDataProvider(provider, cache_dir, refresh=refresh_cache)
    return provider
