"""Atomic S3 publication for private, expiring MVT source layers."""

from __future__ import annotations

import asyncio
import logging
import re
import secrets
import shutil
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from .artifacts import ArtifactTooLarge, SourceArtifact, write_source

logger = logging.getLogger(__name__)

DEFAULT_TTL_SECONDS = 24 * 60 * 60
_CAPABILITY = re.compile(r"[A-Za-z0-9_-]{43}\Z")
_SOURCE_CONTENT_TYPE = "application/vnd.apache.parquet"
_MANIFEST_CONTENT_TYPE = "application/json"
_DELETE_ATTEMPTS = 3

SourceWriter = Callable[..., SourceArtifact]
Clock = Callable[[], datetime]
TokenFactory = Callable[[], str]


class LayerCleanupError(RuntimeError):
    """The two known source objects could not be removed during rollback."""


def _utc_timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def validate_capability(value: str) -> str:
    if not isinstance(value, str) or _CAPABILITY.fullmatch(value) is None:
        raise ValueError("capability must be a 43-character URL-safe token")
    return value


def capability_fingerprint(capability: str) -> str:
    validate_capability(capability)
    return sha256(capability.encode("ascii")).hexdigest()[:12]


def _base_url(value: str, field: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field} must be a non-empty URL base")
    if any(marker in value for marker in ("{", "}", "?", "#")):
        raise ValueError(f"{field} must not contain templates, a query, or a fragment")
    parsed = urlsplit(value)
    if parsed.scheme:
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(f"{field} must be an HTTP(S) URL or an absolute path")
    elif not value.startswith("/"):
        raise ValueError(f"{field} must be an HTTP(S) URL or an absolute path")
    return value.rstrip("/")


@dataclass(frozen=True, slots=True)
class PublishedLayer:
    capability: str
    url: str
    dispose_url: str
    expires_at: datetime
    byte_count: int
    min_zoom: int
    max_zoom: int

    @property
    def url_expires_at(self) -> str:
        return _utc_timestamp(self.expires_at)


class S3LayerPublisher:
    """Upload source first and expose a layer only after its manifest commits."""

    def __init__(
        self,
        s3_client: Any,
        bucket: str,
        *,
        tile_base_url: str = "/data/tiles",
        dispose_base_url: str = "/data/layers",
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
        clock: Clock | None = None,
        token_factory: TokenFactory | None = None,
        source_writer: SourceWriter = write_source,
        temp_root: Path | None = None,
    ) -> None:
        if not isinstance(bucket, str) or not bucket.strip():
            raise ValueError("bucket must be a non-empty string")
        if type(ttl_seconds) is not int or ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be a positive integer")
        self._s3 = s3_client
        self._bucket = bucket
        self._tile_base_url = _base_url(tile_base_url, "tile_base_url")
        self._dispose_base_url = _base_url(dispose_base_url, "dispose_base_url")
        self._ttl = timedelta(seconds=ttl_seconds)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._source_writer = source_writer
        self._temp_root = Path(temp_root) if temp_root is not None else None

    async def publish_layer(
        self,
        result_id: str,
        features: list[dict[str, Any]],
        *,
        complete: bool = True,
    ) -> PublishedLayer | None:
        del result_id
        capability = validate_capability(self._token_factory())
        fingerprint = capability_fingerprint(capability)
        expires_at = self._expiry()
        prefix = f"layers/{capability}"
        source_key = f"{prefix}/source.parquet"
        manifest_key = f"{prefix}/manifest.json"
        private = Path(tempfile.mkdtemp(prefix="sgs-layer-", dir=self._temp_root))
        source_path = private / "source.parquet"
        upload_started = False
        try:
            artifact = await self._blocking(
                self._source_writer,
                features,
                source_path,
                expires_at=expires_at,
                complete=complete,
            )
            upload_started = True
            await self._blocking(
                self._s3.upload_file,
                str(artifact.path),
                self._bucket,
                source_key,
                ExtraArgs={
                    "ContentType": _SOURCE_CONTENT_TYPE,
                    "Metadata": {
                        "source-sha256": artifact.manifest.source_sha256,
                        "source-bytes": str(artifact.manifest.source_bytes),
                    },
                },
            )
            await self._blocking(
                self._s3.put_object,
                Bucket=self._bucket,
                Key=manifest_key,
                Body=artifact.manifest.to_json(),
                ContentType=_MANIFEST_CONTENT_TYPE,
            )
        except asyncio.CancelledError:
            if upload_started:
                await self._rollback(capability, fingerprint)
            raise
        except ArtifactTooLarge:
            logger.warning("layer source exceeded its bound fp=%s", fingerprint)
            return None
        except Exception:
            if upload_started:
                try:
                    await self._rollback(capability, fingerprint)
                except LayerCleanupError:
                    logger.error("layer publication rollback incomplete fp=%s", fingerprint)
            logger.error("layer publication failed fp=%s", fingerprint)
            return None
        finally:
            await self._blocking(shutil.rmtree, private, True)

        published = PublishedLayer(
            capability=capability,
            url=f"{self._tile_base_url}/{capability}/{{z}}/{{x}}/{{y}}.mvt",
            dispose_url=f"{self._dispose_base_url}/{capability}",
            expires_at=artifact.manifest.expires_at,
            byte_count=artifact.byte_count,
            min_zoom=artifact.manifest.min_zoom,
            max_zoom=artifact.manifest.max_zoom,
        )
        logger.info("published MVT source fp=%s bytes=%d", fingerprint, artifact.byte_count)
        return published

    def _expiry(self) -> datetime:
        now = self._clock()
        if not isinstance(now, datetime) or now.tzinfo is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return now.astimezone(UTC) + self._ttl

    async def _rollback(self, capability: str, fingerprint: str) -> None:
        pending = [
            {"Key": f"layers/{capability}/source.parquet"},
            {"Key": f"layers/{capability}/manifest.json"},
        ]
        for _ in range(_DELETE_ATTEMPTS):
            try:
                response = await self._blocking(
                    self._s3.delete_objects,
                    Bucket=self._bucket,
                    Delete={"Objects": pending, "Quiet": True},
                )
            except asyncio.CancelledError:
                raise
            except Exception:
                raise LayerCleanupError(f"layer rollback failed fp={fingerprint}") from None
            failed_keys = {
                error.get("Key")
                for error in response.get("Errors", [])
                if isinstance(error, dict) and isinstance(error.get("Key"), str)
            }
            if not failed_keys:
                return
            pending = [item for item in pending if item["Key"] in failed_keys]
        raise LayerCleanupError(f"layer rollback incomplete fp={fingerprint}")

    @staticmethod
    async def _blocking(function: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            try:
                await task
            except BaseException:
                pass
            raise
