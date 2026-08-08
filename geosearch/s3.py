"""Layer storage on S3, with a local stand-in for the bucket we cannot reach yet.

The production bucket is `sgs-llm-data-259789526488` (infra/backend-foundation.yaml),
whose write policy is attached to the backend's ECS TaskRole only - this server has no
credentials for it. So the same boto3 code points at a moto server on localhost
instead. Only `GEOSEARCH_S3_ENDPOINT` differs between the two; unset it in production
and the identical calls go to real S3.

moto runs in-process (ThreadedMotoServer) rather than as a container: the frontend
fetches layer URLs straight from the browser, so the store has to be reachable over
HTTP, but nothing about that requires a second process to babysit.
"""

from __future__ import annotations

import json
import logging
import os
import socket
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BUCKET = os.environ.get("GEOSEARCH_S3_BUCKET", "sgs-llm-data-local")
REGION = os.environ.get("GEOSEARCH_S3_REGION", "eu-central-1")

# How long a published layer URL stays valid. The frontend fetches it immediately on
# receiving the tool result, so this only has to outlive one conversation turn.
URL_TTL = 3600


def _free_port(preferred: int = 5000) -> int:
    """Preferred port if nothing holds it, otherwise one the OS picks.

    Never displaces a listener: port 5000 is macOS AirPlay Receiver's by default, and
    the machine this runs on already has its own services on the nearby ports.
    """
    with socket.socket() as probe:
        try:
            probe.bind(("127.0.0.1", preferred))
            return preferred
        except OSError:
            pass
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


class S3Store:
    """Publishes GeoJSON and hands back a URL the browser can fetch."""

    def __init__(self, endpoint_url: str | None = None, bucket: str = BUCKET) -> None:
        import boto3

        self.bucket = bucket
        self.endpoint_url = endpoint_url or os.environ.get("GEOSEARCH_S3_ENDPOINT") or None
        kwargs: dict[str, Any] = {"region_name": REGION}
        if self.endpoint_url:
            # moto accepts anything, but boto3 refuses to sign without credentials, and
            # the ambient AWS profile must not leak into what is meant to be a local stub.
            kwargs.update(
                endpoint_url=self.endpoint_url,
                aws_access_key_id="local",
                aws_secret_access_key="local",
            )
        self.client = boto3.client("s3", **kwargs)

    def ensure_bucket(self) -> None:
        """Creates the bucket and opens it for browser reads. Local endpoint only.

        Deliberately a no-op against real S3: that bucket is managed by CloudFormation
        with public access blocked on all four settings, and an application quietly
        rewriting its CORS policy is how a private bucket becomes a public one.
        """
        if not self.endpoint_url:
            return
        try:
            self.client.create_bucket(
                Bucket=self.bucket,
                CreateBucketConfiguration={"LocationConstraint": REGION},
            )
        except self.client.exceptions.BucketAlreadyOwnedByYou:
            pass
        self.client.put_bucket_cors(
            Bucket=self.bucket,
            CORSConfiguration={
                "CORSRules": [
                    {
                        "AllowedMethods": ["GET", "HEAD"],
                        "AllowedOrigins": ["*"],
                        "AllowedHeaders": ["*"],
                    }
                ]
            },
        )

    def put_geojson(self, key: str, collection: dict[str, Any]) -> str:
        body = json.dumps(collection, ensure_ascii=False).encode("utf-8")
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType="application/geo+json",
        )
        logger.info("s3://%s/%s (%d bytes)", self.bucket, key, len(body))
        return self.url(key)

    def get_geojson(self, key: str) -> dict[str, Any]:
        body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        parsed: dict[str, Any] = json.loads(body)
        return parsed

    def url(self, key: str) -> str:
        presigned: str = self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=URL_TTL,
        )
        return presigned

    def seed_from_dir(self, directory: Path) -> int:
        """Uploads a directory tree into the bucket, preserving relative paths as keys.

        moto keeps everything in memory, so a restart empties the bucket. The build
        writes the division layers to disk as well, and this replays them - which is
        what makes the local bucket behave like the durable one it stands in for.
        Against real S3 there is nothing to replay, and this is never called.
        """
        directory = Path(directory)
        if not directory.is_dir():
            return 0
        count = 0
        for path in sorted(directory.rglob("*.geojson")):
            self.client.put_object(
                Bucket=self.bucket,
                Key=str(path.relative_to(directory)),
                Body=path.read_bytes(),
                ContentType="application/geo+json",
            )
            count += 1
        logger.info("seeded %d objects into s3://%s from %s", count, self.bucket, directory)
        return count

    async def publish_geojson(self, name: str, feature_collection: dict[str, Any]) -> str | None:
        """The interface mcp_dummy's `artifacts` object exposes, so the eval harness and
        the backend's own ArtifactStore stay drop-in replacements for this."""
        try:
            return self.put_geojson(f"layers/{name}", feature_collection)
        except Exception:
            logger.exception("could not publish %s", name)
            return None


class BoundaryStore:
    """The division boundaries, read from the image instead of from a bucket.

    They are build output - 6272 polygons that change when the build runs and at no other
    time - so they ship with the code that was built against them. Two things follow.
    The container answers its first request as fast as its thousandth, with no seeding
    step and no bucket to be empty. And they stay out of `sgs-llm-data-*`, whose
    `expire-data-layers` lifecycle rule (infra/backend-foundation.yaml) exists to expire
    *published* layers after 30 days and cannot tell these from those - the rule is right,
    the boundaries were simply the wrong thing to keep beside them.

    Only `get_geojson` is needed: display_division reads the polygon from here and
    republishes it through `artifacts`, which is what the browser fetches.
    """

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory).resolve()

    def get_geojson(self, key: str) -> dict[str, Any]:
        # Keys come from the build's own `s3_key` column, never from a user. They reach
        # the filesystem now rather than an object store, so the containment check is
        # cheap insurance against that ever stopping being true.
        path = (self.directory / key).resolve()
        if not path.is_relative_to(self.directory):
            raise ValueError(f"boundary key escapes {self.directory}: {key!r}")
        parsed: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return parsed

    def count(self) -> int:
        return sum(1 for _ in self.directory.rglob("*.geojson"))


_moto_server: Any = None


def start_local_s3(seed_dir: Path | None = None) -> S3Store:
    """Boots moto, creates the bucket, returns a store pointed at it.

    Idempotent: repeated calls reuse the running server rather than starting a second.
    """
    global _moto_server
    if _moto_server is None:
        from moto.server import ThreadedMotoServer

        # `verbose=False` only silences moto's own banner; the WSGI layer underneath
        # still logs a line per request, and seeding is ~2300 PUTs.
        logging.getLogger("werkzeug").setLevel(logging.WARNING)

        port = _free_port()
        _moto_server = ThreadedMotoServer(port=port, verbose=False)
        _moto_server.start()
        os.environ["GEOSEARCH_S3_ENDPOINT"] = f"http://127.0.0.1:{port}"
        logger.info("local S3 (moto) on %s", os.environ["GEOSEARCH_S3_ENDPOINT"])

    store = S3Store(endpoint_url=os.environ["GEOSEARCH_S3_ENDPOINT"])
    store.ensure_bucket()
    if seed_dir is not None:
        store.seed_from_dir(seed_dir)
    return store


def stop_local_s3() -> None:
    global _moto_server
    if _moto_server is not None:
        _moto_server.stop()
        _moto_server = None
