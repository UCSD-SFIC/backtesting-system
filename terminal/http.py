"""One rate-limited, retrying HTTP fetcher shared by every SEC request.

Other workstreams should reuse this (through `SecClient` / `SourceCache`)
instead of calling the SEC directly, so the whole app stays under one limit.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable

import httpx

from terminal.errors import RateLimitedError, UpstreamError, UpstreamNotFoundError

logger = logging.getLogger(__name__)

RETRY_STATUS = {429, 500, 502, 503, 504}


class RateLimiter:
    """Spaces calls at least `1 / max_per_second` apart across all threads."""

    def __init__(
        self,
        max_per_second: float,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if max_per_second <= 0:
            raise ValueError("max_per_second must be positive")
        self._interval = 1.0 / max_per_second
        self._clock = clock
        self._sleep = sleep
        self._next_allowed = 0.0
        self._lock = threading.Lock()

    def acquire(self) -> None:
        with self._lock:
            now = self._clock()
            wait = self._next_allowed - now
            if wait > 0:
                self._sleep(wait)
                now += wait
            self._next_allowed = now + self._interval


def _retry_after_seconds(response: httpx.Response) -> float | None:
    value = response.headers.get("retry-after")
    if value is None:
        return None
    try:
        return max(0.0, float(value))
    except ValueError:
        return None


class HttpFetcher:
    """GET a URL with identification headers, rate limiting, and retries."""

    def __init__(
        self,
        user_agent: Callable[[], str],
        limiter: RateLimiter,
        *,
        transport: httpx.BaseTransport | None = None,
        max_attempts: int = 3,
        backoff_seconds: float = 0.5,
        max_backoff_seconds: float = 8.0,
        timeout_seconds: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._user_agent = user_agent
        self._limiter = limiter
        self._client = httpx.Client(
            transport=transport, timeout=timeout_seconds, follow_redirects=True
        )
        self._max_attempts = max_attempts
        self._backoff = backoff_seconds
        self._max_backoff = max_backoff_seconds
        self._sleep = sleep

    def close(self) -> None:
        self._client.close()

    def get(self, url: str) -> bytes:
        # Raises ConfigurationError before any network call if unset.
        headers = {"User-Agent": self._user_agent(), "Accept": "application/json"}
        last_status: int | None = None
        retry_after: float | None = None
        last_error = "no response"

        for attempt in range(self._max_attempts):
            self._limiter.acquire()
            try:
                response = self._client.get(url, headers=headers)
            except httpx.HTTPError as exc:
                last_status, retry_after = None, None
                last_error = f"{type(exc).__name__}: {exc}"
            else:
                if response.status_code == 200:
                    return response.content
                if response.status_code == 404:
                    raise UpstreamNotFoundError(f"{url} returned 404")
                if response.status_code == 403:
                    raise UpstreamError(
                        f"{url} returned 403. The SEC blocks requests without a descriptive "
                        "User-Agent; check SEC_USER_AGENT (name plus contact email)."
                    )
                if response.status_code not in RETRY_STATUS:
                    raise UpstreamError(f"{url} returned HTTP {response.status_code}")
                last_status = response.status_code
                retry_after = _retry_after_seconds(response)
                last_error = f"HTTP {response.status_code}"

            if attempt + 1 < self._max_attempts:
                delay = self._backoff * (2**attempt)
                if retry_after is not None:
                    delay = max(delay, retry_after)
                delay = min(delay, self._max_backoff)
                logger.warning("GET %s failed (%s); retrying in %.1fs", url, last_error, delay)
                self._sleep(delay)

        if last_status == 429:
            raise RateLimitedError(
                f"{url} is rate limiting requests", retry_after=retry_after or self._max_backoff
            )
        raise UpstreamError(f"{url} failed after {self._max_attempts} attempts: {last_error}")
