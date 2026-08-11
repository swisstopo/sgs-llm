"""Strict private-S3 repository for expiring GeoParquet source layers."""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any

from botocore.exceptions import ClientError
from tile_server.model import LayerManifest, SourceRef

_CAPABILITY = re.compile(r"[A-Za-z0-9_-]{43}\Z")
_DEFAULT_MANIFEST_MAX_BYTES = 64 * 1024
_DELETE_ATTEMPTS = 3
Clock = Callable[[], datetime]


class LayerStoreError(RuntimeError):
    """Base class for redacted private-layer storage failures."""


class LayerMissing(LayerStoreError):
    """The capability has no committed, non-deleted layer."""


class LayerExpired(LayerStoreError):
    """The committed layer lifetime has ended."""


class LayerInvalid(LayerStoreError):
    """A committed private object failed its strict trust contract."""


class LayerDeleteError(LayerStoreError):
    """Tombstone-first layer cleanup did not finish."""


def validate_capability(value: str) -> str:
    if not isinstance(value, str) or _CAPABILITY.fullmatch(value) is None:
        raise ValueError("capability must be a 43-character URL-safe token")
    return value


def capability_fingerprint(capability: str) -> str:
    validate_capability(capability)
    return sha256(capability.encode("ascii")).hexdigest()[:12]


def _is_missing(error: ClientError) -> bool:
    response = error.response
    status = response.get("ResponseMetadata", {}).get("HTTPStatusCode")
    code = response.get("Error", {}).get("Code")
    return status == 404 or code in {"404", "NoSuchKey", "NotFound"}


class LayerStore:
    """Read immutable source metadata and tombstone/delete known layer objects."""

    def __init__(
        self,
        s3_client: Any,
        bucket: str,
        *,
        clock: Clock | None = None,
        manifest_max_bytes: int = _DEFAULT_MANIFEST_MAX_BYTES,
    ) -> None:
        if not isinstance(bucket, str) or not bucket.strip():
            raise ValueError("bucket must be a non-empty string")
        if type(manifest_max_bytes) is not int or manifest_max_bytes <= 0:
            raise ValueError("manifest_max_bytes must be a positive integer")
        self._s3 = s3_client
        self._bucket = bucket
        self._clock = clock or (lambda: datetime.now(UTC))
        self._manifest_max_bytes = manifest_max_bytes

    def manifest(self, capability: str) -> LayerManifest:
        capability = validate_capability(capability)
        fingerprint = capability_fingerprint(capability)
        if self._tombstoned(capability, fingerprint):
            raise LayerMissing(f"layer is deleted fp={fingerprint}")
        key = f"layers/{capability}/manifest.json"
        try:
            response = self._s3.get_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if _is_missing(exc):
                raise LayerMissing(f"layer is not committed fp={fingerprint}") from None
            raise LayerInvalid(f"manifest read failed fp={fingerprint}") from None
        except Exception:
            raise LayerInvalid(f"manifest read failed fp={fingerprint}") from None

        body = response.get("Body")
        length = response.get("ContentLength")
        encoded = b""
        failed = (
            type(length) is not int
            or length < 0
            or length > self._manifest_max_bytes
            or body is None
        )
        if not failed:
            try:
                encoded = body.read(self._manifest_max_bytes + 1)
            except Exception:
                failed = True
        if not self._close_body(body):
            failed = True
        if (
            failed
            or not isinstance(encoded, bytes)
            or len(encoded) != length
            or len(encoded) > self._manifest_max_bytes
        ):
            raise LayerInvalid(f"manifest is invalid fp={fingerprint}")
        try:
            current = LayerManifest.from_json(encoded)
        except ValueError:
            raise LayerInvalid(f"manifest is invalid fp={fingerprint}") from None
        if current.expires_at <= self._now():
            raise LayerExpired(f"layer has expired fp={fingerprint}")
        if self._tombstoned(capability, fingerprint):
            raise LayerMissing(f"layer is deleted fp={fingerprint}")
        return current

    def source_ref(self, capability: str, manifest: LayerManifest) -> SourceRef:
        capability = validate_capability(capability)
        fingerprint = capability_fingerprint(capability)
        if self._tombstoned(capability, fingerprint):
            raise LayerMissing(f"layer is deleted fp={fingerprint}")
        key = f"layers/{capability}/source.parquet"
        try:
            response = self._s3.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if _is_missing(exc):
                raise LayerMissing(f"layer source is missing fp={fingerprint}") from None
            raise LayerInvalid(f"source validation failed fp={fingerprint}") from None
        except Exception:
            raise LayerInvalid(f"source validation failed fp={fingerprint}") from None
        metadata = response.get("Metadata")
        if (
            type(metadata) is not dict
            or response.get("ContentLength") != manifest.source_bytes
            or metadata.get("source-sha256") != manifest.source_sha256
            or metadata.get("source-bytes") != str(manifest.source_bytes)
        ):
            raise LayerInvalid(f"source validation failed fp={fingerprint}")
        if self._tombstoned(capability, fingerprint):
            raise LayerMissing(f"layer is deleted fp={fingerprint}")
        return SourceRef(f"s3://{self._bucket}/{key}")

    def delete(self, capability: str) -> None:
        capability = validate_capability(capability)
        fingerprint = capability_fingerprint(capability)
        try:
            self._s3.put_object(
                Bucket=self._bucket,
                Key=f"tombstones/{capability}",
                Body=b"deleted",
                ContentType="application/octet-stream",
            )
        except Exception:
            raise LayerDeleteError(f"layer tombstone failed fp={fingerprint}") from None

        pending = [
            {"Key": f"layers/{capability}/source.parquet"},
            {"Key": f"layers/{capability}/manifest.json"},
        ]
        for _ in range(_DELETE_ATTEMPTS):
            try:
                response = self._s3.delete_objects(
                    Bucket=self._bucket,
                    Delete={"Objects": pending, "Quiet": True},
                )
            except Exception:
                raise LayerDeleteError(f"layer cleanup failed fp={fingerprint}") from None
            failed_keys = {
                error.get("Key")
                for error in response.get("Errors", [])
                if isinstance(error, dict) and isinstance(error.get("Key"), str)
            }
            if not failed_keys:
                return
            pending = [item for item in pending if item["Key"] in failed_keys]
        raise LayerDeleteError(f"layer cleanup incomplete fp={fingerprint}")

    def _tombstoned(self, capability: str, fingerprint: str) -> bool:
        try:
            self._s3.head_object(Bucket=self._bucket, Key=f"tombstones/{capability}")
        except ClientError as exc:
            if _is_missing(exc):
                return False
            raise LayerInvalid(f"tombstone check failed fp={fingerprint}") from None
        except Exception:
            raise LayerInvalid(f"tombstone check failed fp={fingerprint}") from None
        return True

    def _now(self) -> datetime:
        value = self._clock()
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise LayerInvalid("storage clock is invalid")
        return value.astimezone(UTC)

    @staticmethod
    def _close_body(body: Any) -> bool:
        if body is None:
            return True
        close = getattr(body, "close", None)
        if not callable(close):
            return False
        try:
            close()
        except Exception:
            return False
        return True
