"""Per-client limits for the public chat endpoint.

The endpoint is unauthenticated by design (docs/protocol.md), and every turn spends
Bedrock tokens, so the practical protection is throttling rather than a key. Both
structures are keyed by client address and hold no state that outlives the process
- a single pilot task means no shared store is needed.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator, MutableMapping
from contextlib import contextmanager
from dataclasses import dataclass, field

# Above this many tracked keys, `forget` also drops every refilled bucket.
_SWEEP_ABOVE = 1024


@dataclass
class _Bucket:
    tokens: float
    updated_at: float


class RateLimiter:
    """Token bucket per key: `capacity` messages, refilled over one minute."""

    def __init__(self, capacity: int, *, now: Callable[[], float] | None = None) -> None:
        self._capacity = float(max(capacity, 1))
        self._refill_per_second = self._capacity / 60.0
        self._now = now or time.monotonic
        self._buckets: MutableMapping[str, _Bucket] = {}

    def allow(self, key: str) -> bool:
        """Consumes one token, returning False when the caller is over budget."""
        now = self._now()
        bucket = self._buckets.get(key)
        if bucket is None:
            self._buckets[key] = _Bucket(tokens=self._capacity - 1.0, updated_at=now)
            return True

        elapsed = max(now - bucket.updated_at, 0.0)
        bucket.tokens = min(self._capacity, bucket.tokens + elapsed * self._refill_per_second)
        bucket.updated_at = now
        if bucket.tokens < 1.0:
            return False
        bucket.tokens -= 1.0
        return True

    def _replenished(self, bucket: _Bucket, now: float) -> bool:
        elapsed = max(now - bucket.updated_at, 0.0)
        return bucket.tokens + elapsed * self._refill_per_second >= self._capacity

    def forget(self, key: str) -> None:
        """Drops a key's bucket only once it has refilled.

        Dropping it unconditionally let a client reset its own allowance by reconnecting,
        since this is called when their last connection closes.
        """
        now = self._now()
        bucket = self._buckets.get(key)
        if bucket is not None and self._replenished(bucket, now):
            del self._buckets[key]
        if len(self._buckets) > _SWEEP_ABOVE:
            self._sweep(now)

    def _sweep(self, now: float) -> None:
        """Drops every refilled bucket, so keys held back by `forget` cannot accumulate."""
        for key in [k for k, b in self._buckets.items() if self._replenished(b, now)]:
            del self._buckets[key]


class TooManyConnections(Exception):
    pass


@dataclass
class ConnectionRegistry:
    """Caps concurrent connections per client address."""

    limit: int
    _counts: dict[str, int] = field(default_factory=dict)

    @contextmanager
    def hold(self, key: str) -> Iterator[None]:
        current = self._counts.get(key, 0)
        if current >= self.limit:
            raise TooManyConnections(key)
        self._counts[key] = current + 1
        try:
            yield
        finally:
            remaining = self._counts.get(key, 1) - 1
            if remaining <= 0:
                self._counts.pop(key, None)
            else:
                self._counts[key] = remaining

    def count(self, key: str) -> int:
        return self._counts.get(key, 0)

    def is_idle(self, key: str) -> bool:
        return key not in self._counts
