from __future__ import annotations

import datetime as dt
import inspect
import os
import sys
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from strategy.registry import STRATEGIES

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib  # pyright: ignore[reportMissingImports]


Timespan = Literal["minute", "hour", "2hour", "day", "week", "month"]
ProviderName = Literal["yfinance", "polygon"]


class _StrictModel(BaseModel):
    # Typos in a config file should fail loudly instead of being ignored.
    model_config = ConfigDict(extra="forbid")


class DataConfig(_StrictModel):
    provider: ProviderName = "yfinance"
    cache_dir: str | None = "history_cache"
    refresh_cache: bool = False
    validate_data: bool = True


class ExecutionConfig(_StrictModel):
    # Simulated cost per unit of turnover, in basis points of portfolio value.
    cost_bps: float = Field(default=0.0, ge=0, le=500)


class StrategyConfig(_StrictModel):
    name: str
    params: dict[str, Any] = Field(default_factory=dict)

    @field_validator("name")
    @classmethod
    def _known_strategy(cls, name: str) -> str:
        if name not in STRATEGIES:
            raise ValueError(f"unknown strategy; choose one of: {', '.join(sorted(STRATEGIES))}")
        return name


class RunConfig(_StrictModel):
    tickers: list[str] = Field(min_length=1)
    timespan: Timespan = "day"
    start: dt.date
    end: dt.date
    benchmark: str | None = None
    risk_free_rate: float = Field(default=0.02, ge=-0.05, le=0.5)
    strategy: StrategyConfig
    data: DataConfig = Field(default_factory=DataConfig)
    execution: ExecutionConfig = Field(default_factory=ExecutionConfig)

    @field_validator("tickers")
    @classmethod
    def _normalize_tickers(cls, tickers: list[str]) -> list[str]:
        cleaned = [ticker.strip().upper() for ticker in tickers]
        if any(not ticker for ticker in cleaned):
            raise ValueError("tickers cannot be blank")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("tickers must be unique")
        return cleaned

    @model_validator(mode="after")
    def _check_dates_and_benchmark(self) -> RunConfig:
        if self.end <= self.start:
            raise ValueError("end must be after start")
        if self.benchmark is None:
            self.benchmark = self.tickers[0]
            return self

        self.benchmark = self.benchmark.strip().upper()
        if self.benchmark in self.tickers:
            return self
        # Strategies that accept a `benchmark` parameter fetch it for comparison
        # without ever holding it, so it can sit outside the investable tickers.
        parameters = inspect.signature(STRATEGIES[self.strategy.name]).parameters
        if "benchmark" not in parameters:
            raise ValueError(
                "benchmark must be one of the tickers for strategy " + repr(self.strategy.name)
            )
        self.strategy.params.setdefault("benchmark", self.benchmark)
        return self


# Environment variables that override config values, applied before validation.
ENV_OVERRIDES = {
    "DATA_PROVIDER": ("data", "provider"),
    "BACKTEST_CACHE_DIR": ("data", "cache_dir"),
}


def load_config(path: str | Path, overrides: dict[str, Any] | None = None) -> RunConfig:
    """
    Load a TOML run config.

    Precedence, lowest to highest: file values, environment variables in
    `ENV_OVERRIDES`, then `overrides` (dotted keys such as "data.provider",
    used for CLI flags). Values of None in `overrides` are ignored.
    """
    with open(path, "rb") as file:
        raw: dict[str, Any] = tomllib.load(file)

    for env_name, keys in ENV_OVERRIDES.items():
        value = os.getenv(env_name)
        if value:
            _set_dotted(raw, keys, value)

    for dotted_key, value in (overrides or {}).items():
        if value is not None:
            _set_dotted(raw, tuple(dotted_key.split(".")), value)

    return RunConfig.model_validate(raw)


def _set_dotted(raw: dict[str, Any], keys: tuple[str, ...], value: Any) -> None:
    target = raw
    for key in keys[:-1]:
        target = target.setdefault(key, {})
    target[keys[-1]] = value
