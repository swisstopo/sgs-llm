"""Focused orchestration tests for on-demand MVT generation."""

from __future__ import annotations

import asyncio
import threading
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from tile_server.model import LayerManifest, RenderLimits, RenderTimedOut, SourceRef, TileCoord

from app.config import Settings
from app.tiles.cache import TileCache
from app.tiles.service import RenderBusy, TileRenderFailed, TileService
from app.tiles.store import LayerInvalid, LayerMissing

TOKEN = "A" * 43
NOW = datetime.now(UTC)
COORD = TileCoord(z=1, x=1, y=0)
OTHER_COORD = TileCoord(z=1, x=0, y=1)
BODY = b"mvt"
LIMITS = RenderLimits(
    memory_bytes=1024 * 1024,
    max_spill_bytes=1024 * 1024,
    timeout_seconds=1,
    max_rows_examined=100,
    max_features_encoded=100,
    max_mvt_bytes=1024,
)


def manifest() -> LayerManifest:
    return LayerManifest(
        schema_version=1,
        created_at=NOW,
        expires_at=NOW + timedelta(hours=1),
        feature_count=1,
        coordinate_count=1,
        complete=True,
        bbox=(7.4, 46.9, 7.5, 47.0),
        crs="OGC:CRS84",
        geometry_type="point",
        min_zoom=0,
        fit_zoom=1,
        max_zoom=2,
        property_columns={"name": "name"},
        property_types={"name": "string"},
        source_sha256="1" * 64,
        source_bytes=100,
    )


class FakeStore:
    def __init__(self) -> None:
        self.current = manifest()
        self.calls: list[str] = []
        self.error: BaseException | None = None
        self.delete_error: BaseException | None = None
        self.delete_started: threading.Event | None = None
        self.delete_release: threading.Event | None = None
        self.thread_ids: list[int] = []

    def manifest(self, capability: str) -> LayerManifest:
        assert capability == TOKEN
        self.calls.append("manifest")
        self.thread_ids.append(threading.get_ident())
        if self.error is not None:
            raise self.error
        return self.current

    def source_ref(self, capability: str, current: LayerManifest) -> SourceRef:
        assert capability == TOKEN
        assert current is self.current
        self.calls.append("source")
        self.thread_ids.append(threading.get_ident())
        return SourceRef(f"s3://bucket/layers/{capability}/source.parquet")

    def delete(self, capability: str) -> None:
        assert capability == TOKEN
        self.calls.append("delete")
        self.thread_ids.append(threading.get_ident())
        if self.delete_started is not None:
            self.delete_started.set()
        if self.delete_release is not None:
            assert self.delete_release.wait(2)
        if self.delete_error is not None:
            raise self.delete_error


def service(store: FakeStore, renderer: Any, **changes: Any) -> TileService:
    return TileService(
        store,
        renderer,
        cache=changes.pop("cache", TileCache(max_entries=8, max_bytes=8192)),
        limits=LIMITS,
        capacity=changes.pop("capacity", 2),
        queue_timeout=changes.pop("queue_timeout", 0.05),
        render_timeout=changes.pop("render_timeout", 1.0),
        total_timeout=changes.pop("total_timeout", 2.0),
        **changes,
    )


def returning(body: bytes = BODY):
    def render(
        source: SourceRef,
        current: LayerManifest,
        coord: TileCoord,
        limits: RenderLimits,
    ) -> bytes:
        assert source.is_s3
        assert current.source_sha256
        assert coord in (COORD, OTHER_COORD)
        assert limits is LIMITS
        return body

    return render


@pytest.mark.asyncio
async def test_one_render_is_shared_by_concurrent_requests() -> None:
    store = FakeStore()
    started = threading.Event()
    release = threading.Event()
    renders = 0

    def renderer(*_args: Any) -> bytes:
        nonlocal renders
        renders += 1
        started.set()
        assert release.wait(2)
        return BODY

    tiles = service(store, renderer)
    first = asyncio.create_task(tiles.tile(TOKEN, COORD))
    assert await asyncio.to_thread(started.wait, 1)
    second = asyncio.create_task(tiles.tile(TOKEN, COORD))
    await asyncio.sleep(0)
    release.set()

    one, two = await asyncio.gather(first, second)
    assert one == two
    assert renders == 1
    assert store.calls == ["manifest", "source"]
    await tiles.close()


@pytest.mark.asyncio
async def test_cache_hit_needs_no_s3_or_renderer_work() -> None:
    store = FakeStore()
    renders = 0

    def renderer(*args: Any) -> bytes:
        nonlocal renders
        renders += 1
        return returning()(*args)

    tiles = service(store, renderer)
    first = await tiles.tile(TOKEN, COORD)
    store.calls.clear()
    second = await tiles.tile(TOKEN, COORD)

    assert second == first
    assert renders == 1
    assert store.calls == []
    await tiles.close()


@pytest.mark.asyncio
async def test_cancelling_one_waiter_does_not_cancel_shared_generation() -> None:
    store = FakeStore()
    started = threading.Event()
    release = threading.Event()

    def renderer(*_args: Any) -> bytes:
        started.set()
        assert release.wait(2)
        return BODY

    tiles = service(store, renderer)
    survivor = asyncio.create_task(tiles.tile(TOKEN, COORD))
    assert await asyncio.to_thread(started.wait, 1)
    cancelled = asyncio.create_task(tiles.tile(TOKEN, COORD))
    await asyncio.sleep(0)
    cancelled.cancel()
    with pytest.raises(asyncio.CancelledError):
        await cancelled
    release.set()

    assert (await survivor).body == BODY
    assert (await tiles.tile(TOKEN, COORD)).body == BODY
    await tiles.close()


@pytest.mark.asyncio
async def test_delete_invalidates_local_tiles_even_when_storage_cleanup_fails() -> None:
    store = FakeStore()
    renders = 0

    def renderer(*_args: Any) -> bytes:
        nonlocal renders
        renders += 1
        return BODY

    tiles = service(store, renderer)
    await tiles.tile(TOKEN, COORD)
    store.delete_error = LayerInvalid("redacted")
    with pytest.raises(LayerInvalid):
        await tiles.delete(TOKEN)
    store.delete_error = None
    await tiles.tile(TOKEN, COORD)

    assert renders == 2
    await tiles.close()


@pytest.mark.asyncio
async def test_delete_prevents_an_inflight_render_from_becoming_visible() -> None:
    store = FakeStore()
    started = threading.Event()
    release = threading.Event()

    def renderer(*_args: Any) -> bytes:
        started.set()
        assert release.wait(2)
        return BODY

    tiles = service(store, renderer)
    pending = asyncio.create_task(tiles.tile(TOKEN, COORD))
    assert await asyncio.to_thread(started.wait, 1)
    await tiles.delete(TOKEN)
    release.set()

    with pytest.raises(LayerMissing):
        await pending
    await tiles.close()


@pytest.mark.asyncio
async def test_request_started_during_delete_cannot_publish_after_delete_finishes() -> None:
    store = FakeStore()
    store.delete_started = threading.Event()
    store.delete_release = threading.Event()
    render_started = threading.Event()
    render_release = threading.Event()

    def renderer(*_args: Any) -> bytes:
        render_started.set()
        assert render_release.wait(2)
        return BODY

    tiles = service(store, renderer)
    deleting = asyncio.create_task(tiles.delete(TOKEN))
    assert await asyncio.to_thread(store.delete_started.wait, 1)
    pending = asyncio.create_task(tiles.tile(TOKEN, COORD))
    assert await asyncio.to_thread(render_started.wait, 1)
    store.delete_release.set()
    await deleting
    render_release.set()

    with pytest.raises(LayerMissing):
        await pending
    await tiles.close()


@pytest.mark.asyncio
async def test_render_capacity_is_global_and_bounded() -> None:
    store = FakeStore()
    started = threading.Event()
    release = threading.Event()

    def renderer(*_args: Any) -> bytes:
        started.set()
        assert release.wait(2)
        return BODY

    tiles = service(store, renderer, capacity=1, queue_timeout=0.01)
    first = asyncio.create_task(tiles.tile(TOKEN, COORD))
    assert await asyncio.to_thread(started.wait, 1)
    with pytest.raises(RenderBusy):
        await tiles.tile(TOKEN, OTHER_COORD)
    release.set()
    await first
    await tiles.close()


@pytest.mark.asyncio
async def test_render_timeout_is_reported_while_close_still_drains_worker() -> None:
    store = FakeStore()
    release = threading.Event()

    def renderer(*_args: Any) -> bytes:
        assert release.wait(2)
        return BODY

    tiles = service(store, renderer, render_timeout=0.01)
    with pytest.raises(RenderTimedOut):
        await tiles.tile(TOKEN, COORD)
    release.set()
    await tiles.close()


@pytest.mark.asyncio
async def test_renderer_dependency_text_is_redacted() -> None:
    store = FakeStore()

    def renderer(*_args: Any) -> bytes:
        raise RuntimeError(f"secret {TOKEN}")

    tiles = service(store, renderer)
    with pytest.raises(TileRenderFailed) as caught:
        await tiles.tile(TOKEN, COORD)
    rendered = str(caught.value)
    assert TOKEN not in rendered
    assert "secret" not in rendered
    await tiles.close()


@pytest.mark.asyncio
async def test_store_calls_leave_the_event_loop_thread() -> None:
    store = FakeStore()
    event_loop_thread = threading.get_ident()
    tiles = service(store, returning())

    await tiles.tile(TOKEN, COORD)

    assert store.thread_ids
    assert all(thread_id != event_loop_thread for thread_id in store.thread_ids)
    await tiles.close()


def test_settings_keep_only_runtime_bounds_used_by_the_service() -> None:
    settings = Settings()
    assert settings.tile_render_capacity == 2
    assert settings.tile_io_capacity == 8
    assert settings.tile_cache_max_entries == 256
    assert settings.tile_cache_max_bytes == 256 * 1024 * 1024


@pytest.mark.asyncio
async def test_missing_capability_is_gone_not_cloudfront_spa_404() -> None:
    from app.tiles.router import router

    store = FakeStore()
    store.error = LayerMissing("redacted")
    tiles = service(store, returning())
    app = FastAPI()
    app.include_router(router)
    app.state.tile_service = tiles

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get(f"/data/tiles/{TOKEN}/1/1/0.mvt")

    assert response.status_code == 410
    assert response.headers["cache-control"] == "no-store"
    await tiles.close()
