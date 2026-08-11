"""Bounded async orchestration for trusted private GeoParquet MVT tiles."""

from __future__ import annotations

import asyncio
import math
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Protocol

from tile_server.model import (
    LayerManifest,
    RenderLimits,
    RenderTimedOut,
    SourceInvalid,
    SourceRef,
    TileCoord,
    TileTooLarge,
)
from tile_server.mvt import render_tile

from app.config import Settings
from app.tiles.cache import CachedTile, TileCache
from app.tiles.store import LayerMissing, LayerStore, capability_fingerprint, validate_capability

Renderer = Callable[[SourceRef, LayerManifest, TileCoord, RenderLimits], bytes]


class Store(Protocol):
    def manifest(self, capability: str) -> LayerManifest: ...

    def source_ref(self, capability: str, manifest: LayerManifest) -> SourceRef: ...

    def delete(self, capability: str) -> None: ...


class RenderBusy(RuntimeError):
    """No render slot became available before the short queue deadline."""

    def __init__(self, retry_after: int = 2) -> None:
        self.retry_after = retry_after
        super().__init__(f"tile renderer is busy; retry_after={retry_after}")


class TileIoBusy(RuntimeError):
    """No blocking-I/O slot became available before the short queue deadline."""

    def __init__(self, retry_after: int = 2) -> None:
        self.retry_after = retry_after
        super().__init__(f"tile blocking I/O is busy; retry_after={retry_after}")


class TileTotalTimedOut(RuntimeError):
    """The request stopped waiting; shared generation may still complete."""


class TileRenderFailed(RuntimeError):
    """The renderer failed unexpectedly; dependency text is intentionally hidden."""


@dataclass(frozen=True, slots=True)
class TileResult:
    body: bytes
    etag: str
    expires_at: datetime | None = None
    source_sha256: str = ""


class TileService:
    """Generate one tile per key, share concurrent work, and keep only a small LRU."""

    def __init__(
        self,
        store: Store,
        renderer: Renderer = render_tile,
        *,
        cache: TileCache | None = None,
        limits: RenderLimits | None = None,
        capacity: int = 2,
        queue_timeout: float = 2.0,
        render_timeout: float = 30.0,
        total_timeout: float = 35.0,
        io_capacity: int = 8,
        io_queue_timeout: float = 2.0,
        cache_max_entries: int = 256,
        cache_max_bytes: int = 256 * 1024 * 1024,
    ) -> None:
        for name, integer_value in (("capacity", capacity), ("io_capacity", io_capacity)):
            if type(integer_value) is not int or integer_value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        timeouts = {
            "queue_timeout": queue_timeout,
            "render_timeout": render_timeout,
            "total_timeout": total_timeout,
            "io_queue_timeout": io_queue_timeout,
        }
        for name, timeout_value in timeouts.items():
            if (
                isinstance(timeout_value, bool)
                or not math.isfinite(timeout_value)
                or timeout_value <= 0
            ):
                raise ValueError(f"{name} must be a positive finite number")
        self._store = store
        self._renderer = renderer
        self._limits = limits or RenderLimits()
        self._render_capacity = asyncio.Semaphore(capacity)
        self._io_capacity = asyncio.Semaphore(io_capacity)
        self._queue_timeout = float(queue_timeout)
        self._io_queue_timeout = float(io_queue_timeout)
        self._render_timeout = float(render_timeout)
        self._total_timeout = float(total_timeout)
        self._cache = cache or TileCache(
            max_entries=cache_max_entries,
            max_bytes=cache_max_bytes,
        )
        self._flights: dict[str, asyncio.Task[TileResult]] = {}
        self._generations: dict[str, int] = {}
        self._background: set[asyncio.Task[Any]] = set()
        self._closed = False

    @classmethod
    def from_settings(
        cls,
        store: LayerStore,
        renderer: Renderer = render_tile,
        *,
        cache: TileCache | None = None,
        settings: Settings,
    ) -> TileService:
        limits = RenderLimits(
            threads=settings.tile_duckdb_threads,
            memory_bytes=settings.tile_duckdb_memory_bytes,
            max_spill_bytes=settings.tile_duckdb_max_spill_bytes,
            timeout_seconds=settings.tile_duckdb_timeout_seconds,
            max_rows_examined=settings.tile_duckdb_max_rows_examined,
            max_features_encoded=settings.tile_duckdb_max_features_encoded,
            max_mvt_bytes=settings.tile_duckdb_max_mvt_bytes,
            spill_directory=_optional_path(settings.tile_duckdb_spill_directory),
            extension_directory=_optional_path(settings.tile_duckdb_extension_directory),
            s3_endpoint_url=settings.generated_data_endpoint_url or None,
        )
        return cls(
            store,
            renderer,
            cache=cache,
            limits=limits,
            capacity=settings.tile_render_capacity,
            queue_timeout=settings.tile_queue_timeout_seconds,
            render_timeout=settings.tile_render_timeout_seconds,
            total_timeout=settings.tile_total_timeout_seconds,
            io_capacity=settings.tile_io_capacity,
            io_queue_timeout=settings.tile_io_queue_timeout_seconds,
            cache_max_entries=settings.tile_cache_max_entries,
            cache_max_bytes=settings.tile_cache_max_bytes,
        )

    async def tile(self, capability: str, coord: TileCoord) -> TileResult:
        validate_capability(capability)
        coord.validate(0, 24)
        if self._closed:
            raise RuntimeError("tile service is closed")
        key = self._cache_key(capability, coord)
        cached = self._cache.get(key, now=datetime.now(UTC))
        if cached is not None:
            return self._result_from_cache(cached)

        flight = self._flights.get(key)
        if flight is None:
            generation = self._generations.get(capability, 0)
            flight = asyncio.create_task(self._generate(capability, coord, key, generation))
            self._flights[key] = flight

            def complete(done: asyncio.Task[TileResult]) -> None:
                self._flight_done(key, done)

            flight.add_done_callback(complete)
        try:
            async with asyncio.timeout(self._total_timeout):
                return await asyncio.shield(flight)
        except TimeoutError:
            raise TileTotalTimedOut("tile request reached its total timeout") from None

    async def delete(self, capability: str) -> None:
        validate_capability(capability)
        self._generations[capability] = self._generations.get(capability, 0) + 1
        self._cache.invalidate_namespace(capability)
        try:
            await self._blocking(self._store.delete, capability)
        finally:
            # Also reject work that began after DELETE started but finished after it.
            self._generations[capability] = self._generations.get(capability, 0) + 1
            self._cache.invalidate_namespace(capability)

    async def close(self) -> None:
        self._closed = True
        while self._flights or self._background:
            tasks = tuple(self._flights.values()) + tuple(self._background)
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            else:
                await asyncio.sleep(0)
        self._cache.clear()

    async def _generate(
        self,
        capability: str,
        coord: TileCoord,
        key: str,
        generation: int,
    ) -> TileResult:
        manifest = await self._blocking(self._store.manifest, capability)
        coord.validate(manifest.min_zoom, manifest.max_zoom)
        source = await self._blocking(self._store.source_ref, capability, manifest)
        body = await self._render(capability, source, manifest, coord)
        if generation != self._generations.get(capability, 0):
            raise LayerMissing(f"layer was deleted fp={capability_fingerprint(capability)}")
        result = self._result(body, manifest, coord)
        self._cache.put(
            key,
            namespace=capability,
            value=CachedTile(
                body=result.body,
                etag=result.etag,
                expires_at=result.expires_at,
                source_sha256=result.source_sha256,
            ),
        )
        return result

    async def _render(
        self,
        capability: str,
        source: SourceRef,
        manifest: LayerManifest,
        coord: TileCoord,
    ) -> bytes:
        try:
            await asyncio.wait_for(
                self._render_capacity.acquire(),
                timeout=self._queue_timeout,
            )
        except TimeoutError:
            raise RenderBusy() from None
        worker = asyncio.create_task(
            asyncio.to_thread(self._renderer, source, manifest, coord, self._limits)
        )
        transferred = False
        try:
            try:
                async with asyncio.timeout(self._render_timeout):
                    return await asyncio.shield(worker)
            except TimeoutError:
                self._track(worker, self._render_capacity)
                transferred = True
                raise RenderTimedOut("tile render reached its timeout") from None
            except (RenderTimedOut, SourceInvalid, TileTooLarge):
                raise
            except Exception:
                raise TileRenderFailed(
                    f"tile render failed fp={capability_fingerprint(capability)}"
                ) from None
        finally:
            if not transferred:
                self._render_capacity.release()

    async def _blocking(self, function: Callable[..., Any], *args: Any) -> Any:
        try:
            await asyncio.wait_for(self._io_capacity.acquire(), timeout=self._io_queue_timeout)
        except TimeoutError:
            raise TileIoBusy() from None
        worker = asyncio.create_task(asyncio.to_thread(function, *args))
        transferred = False
        try:
            return await asyncio.shield(worker)
        except asyncio.CancelledError:
            self._track(worker, self._io_capacity)
            transferred = True
            raise
        finally:
            if not transferred:
                self._io_capacity.release()

    def _track(self, worker: asyncio.Task[Any], capacity: asyncio.Semaphore) -> None:
        async def finish() -> None:
            with suppress(BaseException):
                await asyncio.shield(worker)
            capacity.release()

        task = asyncio.create_task(finish())
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    def _flight_done(self, key: str, flight: asyncio.Task[TileResult]) -> None:
        if self._flights.get(key) is flight:
            self._flights.pop(key, None)
        if not flight.cancelled():
            with suppress(BaseException):
                flight.exception()

    @staticmethod
    def _cache_key(capability: str, coord: TileCoord) -> str:
        return f"{capability}:{coord.z}/{coord.x}/{coord.y}"

    @staticmethod
    def _result(body: bytes, manifest: LayerManifest, coord: TileCoord) -> TileResult:
        etag_source = f"{manifest.source_sha256}:{coord.z}/{coord.x}/{coord.y}".encode("ascii")
        return TileResult(
            body=body,
            etag=f'"{sha256(etag_source).hexdigest()}"',
            expires_at=manifest.expires_at,
            source_sha256=manifest.source_sha256,
        )

    @staticmethod
    def _result_from_cache(value: CachedTile) -> TileResult:
        return TileResult(
            body=value.body,
            etag=value.etag,
            expires_at=value.expires_at,
            source_sha256=value.source_sha256,
        )


def _optional_path(value: str) -> Path | None:
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        raise ValueError("tile directory settings must be absolute paths")
    return path
