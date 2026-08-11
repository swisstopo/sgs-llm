"""Bounded process-local cache for derived MVT response bytes."""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class CachedTile:
    """The complete response metadata needed for a cache hit."""

    body: bytes
    etag: str
    expires_at: datetime | None
    source_sha256: str


@dataclass(frozen=True, slots=True)
class _Entry:
    namespace: str
    value: CachedTile


class TileCache:
    """An exact-size LRU; derived tiles intentionally do not survive a restart."""

    def __init__(self, *, max_entries: int, max_bytes: int) -> None:
        for name, value in (("max_entries", max_entries), ("max_bytes", max_bytes)):
            if type(value) is not int or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        self._max_entries = max_entries
        self._max_bytes = max_bytes
        self._entries: OrderedDict[str, _Entry] = OrderedDict()
        self._bytes = 0

    @property
    def entry_count(self) -> int:
        return len(self._entries)

    @property
    def byte_count(self) -> int:
        return self._bytes

    def get(self, key: str, *, now: datetime) -> CachedTile | None:
        entry = self._entries.get(key)
        if entry is None:
            return None
        expires_at = entry.value.expires_at
        if expires_at is not None and expires_at <= now:
            self._remove(key)
            return None
        self._entries.move_to_end(key)
        return entry.value

    def put(self, key: str, *, namespace: str, value: CachedTile) -> bool:
        """Cache a complete value, returning false when one tile exceeds the budget."""
        size = len(value.body)
        if size > self._max_bytes:
            return False
        self._remove(key)
        self._entries[key] = _Entry(namespace=namespace, value=value)
        self._bytes += size
        while len(self._entries) > self._max_entries or self._bytes > self._max_bytes:
            _, evicted = self._entries.popitem(last=False)
            self._bytes -= len(evicted.value.body)
        return True

    def invalidate_namespace(self, namespace: str) -> int:
        keys = [key for key, entry in self._entries.items() if entry.namespace == namespace]
        for key in keys:
            self._remove(key)
        return len(keys)

    def clear(self) -> None:
        self._entries.clear()
        self._bytes = 0

    def _remove(self, key: str) -> None:
        entry = self._entries.pop(key, None)
        if entry is not None:
            self._bytes -= len(entry.value.body)
