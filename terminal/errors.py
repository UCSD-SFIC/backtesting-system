"""Errors the research-terminal backend can raise, each with an HTTP mapping.

The API layer turns any `TerminalError` into `{"detail": ..., "code": ...}`
with `status_code`, so callers never see a stack trace or made-up data.
"""

from __future__ import annotations


class TerminalError(Exception):
    code = "terminal_error"
    status_code = 500

    def __init__(self, message: str, *, retry_after: float | None = None):
        super().__init__(message)
        self.message = message
        self.retry_after = retry_after


class UnknownTickerError(TerminalError):
    """The ticker is not in the SEC company directory."""

    code = "unknown_ticker"
    status_code = 404


class DataUnavailableError(TerminalError):
    """The company exists but the source has nothing for this request."""

    code = "data_unavailable"
    status_code = 404


class ConfigurationError(TerminalError):
    """A required setting (for example SEC_USER_AGENT) is missing."""

    code = "not_configured"
    status_code = 503


class UpstreamError(TerminalError):
    """A data source failed and there was no cached copy to fall back on."""

    code = "upstream_error"
    status_code = 502


class UpstreamNotFoundError(UpstreamError):
    """The data source answered 404 for the requested resource."""

    code = "upstream_not_found"


class RateLimitedError(UpstreamError):
    """The data source is throttling us; retry after `retry_after` seconds."""

    code = "rate_limited"
    status_code = 503
