"""Data backend for the SFIC Research Terminal.

Company search, SEC financial data, normalized statements, and price history,
each with its source and refresh time. Start with `TerminalService`.
"""

from terminal.cache import SourceInfo
from terminal.config import Settings
from terminal.errors import (
    ConfigurationError,
    DataUnavailableError,
    RateLimitedError,
    TerminalError,
    UnknownTickerError,
    UpstreamError,
)
from terminal.metrics import METRICS, METRICS_BY_KEY, MetricDefinition
from terminal.sec import SecClient, filing_index_url
from terminal.service import TerminalService
from terminal.statements import NormalizedFact, normalize_company_facts
from terminal.store import Company, TerminalStore

__all__ = [
    "METRICS",
    "METRICS_BY_KEY",
    "Company",
    "ConfigurationError",
    "DataUnavailableError",
    "MetricDefinition",
    "NormalizedFact",
    "RateLimitedError",
    "SecClient",
    "Settings",
    "SourceInfo",
    "TerminalError",
    "TerminalService",
    "TerminalStore",
    "UnknownTickerError",
    "UpstreamError",
    "filing_index_url",
    "normalize_company_facts",
]
