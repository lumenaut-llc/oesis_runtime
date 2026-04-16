"""Thread-safe feed cache with file-backed persistence.

Supports fresh lookups, stale fallback (degraded mode), and TTL-based
expiration. Cache entries are persisted to disk so restarts don't lose
recently-fetched data.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path


@dataclass
class CacheEntry:
    payload: dict
    fetched_at: datetime
    expires_at: datetime


class FeedCache:
    """In-memory cache with optional disk persistence."""

    def __init__(self, cache_dir: str | Path | None = None):
        self._entries: dict[str, CacheEntry] = {}
        self._lock = threading.Lock()
        self._cache_dir = Path(cache_dir) if cache_dir else None
        if self._cache_dir:
            self._cache_dir.mkdir(parents=True, exist_ok=True)
            self._load_from_disk()

    def _now(self) -> datetime:
        return datetime.now(timezone.utc)

    def get(self, feed_key: str) -> dict | None:
        """Return payload if cached and not expired, None otherwise."""
        with self._lock:
            entry = self._entries.get(feed_key)
            if entry is None:
                return None
            if self._now() > entry.expires_at:
                return None
            return dict(entry.payload)

    def get_stale(self, feed_key: str) -> dict | None:
        """Return payload even if expired (for degraded mode). None if never cached."""
        with self._lock:
            entry = self._entries.get(feed_key)
            if entry is None:
                return None
            return dict(entry.payload)

    def put(self, feed_key: str, payload: dict, ttl_seconds: int) -> None:
        """Store a cache entry with the given TTL."""
        now = self._now()
        entry = CacheEntry(
            payload=dict(payload),
            fetched_at=now,
            expires_at=datetime.fromtimestamp(
                now.timestamp() + ttl_seconds, tz=timezone.utc
            ),
        )
        with self._lock:
            self._entries[feed_key] = entry
        if self._cache_dir:
            self._persist_entry(feed_key, entry)

    def _persist_entry(self, feed_key: str, entry: CacheEntry) -> None:
        """Write a single cache entry to disk."""
        path = self._cache_dir / f"{feed_key}.json"
        data = {
            "feed_key": feed_key,
            "payload": entry.payload,
            "fetched_at": entry.fetched_at.isoformat(),
            "expires_at": entry.expires_at.isoformat(),
        }
        serialized = json.dumps(data, indent=2, sort_keys=True)
        fd, temp_name = tempfile.mkstemp(
            dir=str(self._cache_dir), prefix=f".{feed_key}.", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(serialized)
                f.flush()
                os.fsync(f.fileno())
            os.replace(temp_name, path)
        except Exception:
            try:
                os.unlink(temp_name)
            except OSError:
                pass

    def _load_from_disk(self) -> None:
        """Restore cache entries from disk on startup."""
        if not self._cache_dir:
            return
        for path in self._cache_dir.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                entry = CacheEntry(
                    payload=data["payload"],
                    fetched_at=datetime.fromisoformat(data["fetched_at"]),
                    expires_at=datetime.fromisoformat(data["expires_at"]),
                )
                self._entries[data["feed_key"]] = entry
            except (json.JSONDecodeError, KeyError, ValueError):
                continue
