"""Small, process-local cache contract for derived MVT responses."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.tiles.cache import CachedTile, TileCache

NOW = datetime(2026, 8, 11, 10, 0, tzinfo=UTC)


def tile(body: bytes, *, expires_at: datetime | None = None) -> CachedTile:
    return CachedTile(
        body=body,
        etag='"etag"',
        expires_at=expires_at,
        source_sha256="1" * 64,
    )


@pytest.mark.parametrize(
    ("max_entries", "max_bytes"),
    [(0, 1), (-1, 1), (1, 0), (1, -1), (True, 1), (1, True)],
)
def test_bounds_must_be_positive_integers(max_entries: int, max_bytes: int) -> None:
    with pytest.raises(ValueError):
        TileCache(max_entries=max_entries, max_bytes=max_bytes)


def test_put_get_and_empty_tiles_are_real_cache_entries() -> None:
    cache = TileCache(max_entries=2, max_bytes=10)

    assert cache.put("empty", namespace="layer-a", value=tile(b""))
    assert cache.get("empty", now=NOW) == tile(b"")
    assert cache.entry_count == 1
    assert cache.byte_count == 0


def test_lru_evicts_the_oldest_entry_by_count() -> None:
    cache = TileCache(max_entries=2, max_bytes=10)
    cache.put("a", namespace="layer", value=tile(b"a"))
    cache.put("b", namespace="layer", value=tile(b"b"))
    assert cache.get("a", now=NOW) is not None

    cache.put("c", namespace="layer", value=tile(b"c"))

    assert cache.get("a", now=NOW) is not None
    assert cache.get("b", now=NOW) is None
    assert cache.get("c", now=NOW) is not None


def test_byte_limit_evicts_and_oversized_value_is_not_cached() -> None:
    cache = TileCache(max_entries=3, max_bytes=5)
    cache.put("a", namespace="layer", value=tile(b"aaa"))
    cache.put("b", namespace="layer", value=tile(b"bbb"))

    assert cache.get("a", now=NOW) is None
    assert cache.get("b", now=NOW) is not None
    assert cache.byte_count == 3
    assert not cache.put("huge", namespace="layer", value=tile(b"123456"))
    assert cache.get("huge", now=NOW) is None


def test_replacing_an_entry_keeps_exact_accounting() -> None:
    cache = TileCache(max_entries=2, max_bytes=10)
    cache.put("a", namespace="layer", value=tile(b"one"))
    cache.put("a", namespace="layer", value=tile(b"seven!!"))

    assert cache.entry_count == 1
    assert cache.byte_count == 7


def test_expired_entries_are_removed_on_read() -> None:
    cache = TileCache(max_entries=2, max_bytes=10)
    cache.put(
        "expired",
        namespace="layer",
        value=tile(b"old", expires_at=NOW - timedelta(seconds=1)),
    )

    assert cache.get("expired", now=NOW) is None
    assert cache.entry_count == 0
    assert cache.byte_count == 0


def test_namespace_invalidation_does_not_touch_other_layers() -> None:
    cache = TileCache(max_entries=3, max_bytes=10)
    cache.put("a", namespace="layer-a", value=tile(b"a"))
    cache.put("b", namespace="layer-a", value=tile(b"b"))
    cache.put("c", namespace="layer-b", value=tile(b"c"))

    assert cache.invalidate_namespace("layer-a") == 2
    assert cache.get("a", now=NOW) is None
    assert cache.get("b", now=NOW) is None
    assert cache.get("c", now=NOW) is not None


def test_clear_releases_all_memory() -> None:
    cache = TileCache(max_entries=2, max_bytes=10)
    cache.put("a", namespace="layer", value=tile(b"abc"))

    cache.clear()

    assert cache.entry_count == 0
    assert cache.byte_count == 0
