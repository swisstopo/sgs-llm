"""Publishing data-layer artifacts the browser then fetches itself.

Deployed, artifacts go to the data bucket and are handed out as presigned URLs, as
docs/architecture.md#data-layers-from-chat describes. With no bucket configured
(local development, and CI's credential-free smoke test) they are held in memory and
served from /data/<name>, which is the same path the CloudFront `/data/*` behavior
and mock-agent already use - so the frontend needs no special case either way.

GeoJSON only for now: the frontend renders `parquet` as "format not yet supported".
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import OrderedDict

from ..config import Settings

logger = logging.getLogger(__name__)

# Bounded so a long-running task cannot grow without limit when no bucket is set.
_LOCAL_MAX_ENTRIES = 64


class ArtifactStore:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._local: OrderedDict[str, bytes] = OrderedDict()
        self._s3: object | None = None
        self._s3_resolved = False

    @property
    def uses_bucket(self) -> bool:
        return bool(self._settings.data_layer_bucket)

    def _client(self) -> object | None:
        if not self._s3_resolved:
            self._s3_resolved = True
            try:
                import boto3

                self._s3 = boto3.client("s3")
            except Exception:
                logger.warning("s3 unavailable; serving artifacts from memory", exc_info=True)
                self._s3 = None
        return self._s3

    async def publish_geojson(self, name: str, feature_collection: dict[str, object]) -> str | None:
        """Stores one FeatureCollection and returns a path or URL the browser can
        fetch, or None when publishing failed.

        A bucket URL is absolute and presigned; the in-memory fallback returns the
        `/data/<name>` path, which the caller resolves against the public origin.
        """
        body = json.dumps(feature_collection, ensure_ascii=False).encode("utf-8")
        bucket = self._settings.data_layer_bucket
        if not bucket:
            self._local[name] = body
            self._local.move_to_end(name)
            while len(self._local) > _LOCAL_MAX_ENTRIES:
                self._local.popitem(last=False)
            return f"/data/{name}"

        client = self._client()
        if client is None:
            return None
        try:
            await asyncio.to_thread(
                client.put_object,  # type: ignore[attr-defined]
                Bucket=bucket,
                Key=name,
                Body=body,
                ContentType="application/geo+json",
            )
            url: str = await asyncio.to_thread(
                client.generate_presigned_url,  # type: ignore[attr-defined]
                "get_object",
                Params={"Bucket": bucket, "Key": name},
                ExpiresIn=self._settings.data_layer_presign_ttl,
            )
            return url
        except Exception:
            logger.warning("failed to publish artifact %s", name, exc_info=True)
            return None

    def read_local(self, name: str) -> bytes | None:
        return self._local.get(name)
