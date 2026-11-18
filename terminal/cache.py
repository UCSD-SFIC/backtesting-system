"""Disk cache for raw source payloads, with a refresh timestamp on everything.

A payload is reused until its TTL passes. When a refresh fails and an older
copy exists, the older copy is returned and marked `stale` with the error, so
the UI can say "as of <time>, refresh failed" instead of showing nothing or,
worse, something invented.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from terminal.errors import ConfigurationError, UpstreamError, UpstreamNotFoundError
from terminal.http import HttpFetcher
from terminal.store import TerminalStore

logger = logging.getLogger(__name__)

Clock = Callable[[], dt.datetime]

# After a failed refresh, keep serving the stale copy this long before retrying.
STALE_RETRY = dt.timedelta(seconds=60)


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


@dataclass(frozen=True)
class SourceInfo:
    """Where a piece of data came from and when it was retrieved."""

    id: str
    provider: str
    url: str
    retrieved_at: dt.datetime
    stale: bool = False
    error: str | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "provider": self.provider,
            "url": self.url,
            "retrieved_at": self.retrieved_at.astimezone(dt.timezone.utc).isoformat(),
            "stale": self.stale,
            "error": self.error,
            "note": self.note,
        }


def safe_name(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_." else "_" for char in value)


class KeyedLocks:
    """One lock per key so two requests never fetch the same thing at once."""

    def __init__(self) -> None:
        self._guard = threading.Lock()
        self._locks: dict[str, threading.Lock] = {}

    def get(self, key: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(key, threading.Lock())


class SourceCache:
    def __init__(
        self,
        root: Path,
        store: TerminalStore,
        fetcher: HttpFetcher,
        *,
        clock: Clock = utc_now,
    ):
        self._root = Path(root)
        self._store = store
        self._fetcher = fetcher
        self._clock = clock
        self._locks = KeyedLocks()

    def _path(self, source_id: str) -> Path:
        return self._root / f"{safe_name(source_id)}.json"

    def get_json(
        self,
        source_id: str,
        url: str,
        *,
        provider: str,
        ttl: dt.timedelta,
        refresh: bool = False,
        expect: type | None = None,
    ) -> tuple[Any, SourceInfo]:
        """Return the parsed payload and its provenance, fetching if needed.

        Pass `expect=dict` (or `list`) to reject a response of the wrong shape
        before it is cached.
        """
        with self._locks.get(source_id):
            path = self._path(source_id)
            record = self._store.get_fetch(source_id)
            cached = record is not None and path.is_file()
            now = self._clock()

            if cached and record is not None and not refresh:
                if now - record.fetched_at < ttl:
                    return self._read(path), SourceInfo(source_id, provider, url, record.fetched_at)
                if record.last_error_at is not None and now - record.last_error_at < STALE_RETRY:
                    return self._read(path), SourceInfo(
                        source_id, provider, url, record.fetched_at,
                        stale=True, error=record.last_error,
                    )

            try:
                body = self._fetcher.get(url)
                payload = json.loads(body)
                if expect is not None and not isinstance(payload, expect):
                    raise ValueError("unexpected response shape")
            except (UpstreamNotFoundError, ConfigurationError):
                raise
            except (UpstreamError, ValueError) as exc:
                message = str(exc)
                if not cached or record is None:
                    if isinstance(exc, UpstreamError):
                        raise
                    raise UpstreamError(
                        f"{url} returned an unreadable or unexpected response"
                    ) from exc
                logger.warning("Refresh of %s failed, serving cached copy: %s", source_id, message)
                self._store.record_fetch_error(source_id, message, now)
                return self._read(path), SourceInfo(
                    source_id, provider, url, record.fetched_at, stale=True, error=message
                )

            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(body)
            temporary.replace(path)
            self._store.record_fetch(
                source_id, provider=provider, url=url, fetched_at=now, payload_path=str(path)
            )
            return payload, SourceInfo(source_id, provider, url, now)

    @staticmethod
    def _read(path: Path) -> Any:
        return json.loads(path.read_bytes())
