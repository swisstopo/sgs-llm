"""Atomic publication tests for private GeoParquet MVT sources."""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import boto3
import pytest
from moto import mock_aws

from .artifacts import SourceArtifact
from tile_server.model import LayerManifest
from .layer_publisher import PublishedLayer, S3LayerPublisher, capability_fingerprint

NOW = datetime(2026, 8, 11, 10, 0, tzinfo=UTC)
SOURCE = b"PAR1source-bytesPAR1"
CHECKSUM = "a" * 64
FEATURES = [
    {
        "type": "Feature",
        "id": "bern",
        "geometry": {"type": "Point", "coordinates": [7.44, 46.95]},
        "properties": {"name": "Bern"},
    }
]


def writer(
    features: list[dict[str, Any]],
    path: Path,
    *,
    expires_at: datetime,
    complete: bool,
) -> SourceArtifact:
    assert features == FEATURES
    path.write_bytes(SOURCE)
    current = LayerManifest(
        schema_version=1,
        created_at=NOW,
        expires_at=expires_at,
        feature_count=1,
        coordinate_count=1,
        complete=complete,
        bbox=(7.44, 46.95, 7.44, 46.95),
        crs="OGC:CRS84",
        geometry_type="point",
        min_zoom=0,
        fit_zoom=8,
        max_zoom=18,
        property_columns={"name": "name"},
        property_types={"name": "string"},
        source_sha256=CHECKSUM,
        source_bytes=len(SOURCE),
    )
    return SourceArtifact(path, len(SOURCE), CHECKSUM, current)


@pytest.fixture
def s3_bucket():
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="layers-test")
        yield client, "layers-test"


class RecordingS3:
    def __init__(self, client: Any, *, fail_manifest: bool = False) -> None:
        self.client = client
        self.fail_manifest = fail_manifest
        self.operations: list[tuple[str, str]] = []
        self.thread_ids: list[int] = []

    def upload_file(self, filename: str, bucket: str, key: str, **kwargs: Any) -> None:
        self.thread_ids.append(threading.get_ident())
        self.operations.append(("upload", key))
        self.client.upload_file(filename, bucket, key, **kwargs)

    def put_object(self, **kwargs: Any) -> Any:
        self.thread_ids.append(threading.get_ident())
        self.operations.append(("put", kwargs["Key"]))
        if self.fail_manifest and kwargs["Key"].endswith("manifest.json"):
            raise RuntimeError("manifest failed")
        return self.client.put_object(**kwargs)

    def delete_objects(self, **kwargs: Any) -> Any:
        self.thread_ids.append(threading.get_ident())
        for item in kwargs["Delete"]["Objects"]:
            self.operations.append(("delete", item["Key"]))
        return self.client.delete_objects(**kwargs)


def publisher(client: Any, bucket: str, **kwargs: Any) -> S3LayerPublisher:
    return S3LayerPublisher(
        client,
        bucket,
        tile_base_url="/data/tiles",
        ttl_seconds=3600,
        clock=lambda: NOW,
        source_writer=writer,
        **kwargs,
    )


def keys(client: Any, bucket: str) -> list[str]:
    response = client.list_objects_v2(Bucket=bucket)
    return sorted(item["Key"] for item in response.get("Contents", []))


def test_source_is_uploaded_before_manifest_commit(s3_bucket) -> None:
    client, bucket = s3_bucket
    recording = RecordingS3(client)

    published = asyncio.run(publisher(recording, bucket).publish_layer("ignored", FEATURES))

    assert published is not None
    prefix = f"layers/{published.capability}"
    assert recording.operations[:2] == [
        ("upload", f"{prefix}/source.parquet"),
        ("put", f"{prefix}/manifest.json"),
    ]
    head = client.head_object(Bucket=bucket, Key=f"{prefix}/source.parquet")
    assert head["ContentType"] == "application/vnd.apache.parquet"
    assert head["Metadata"] == {
        "source-sha256": CHECKSUM,
        "source-bytes": str(len(SOURCE)),
    }


def test_publication_returns_only_the_backend_tile_route(s3_bucket) -> None:
    client, bucket = s3_bucket
    published = asyncio.run(publisher(client, bucket).publish_layer("ignored", FEATURES))

    assert published == PublishedLayer(
        capability=published.capability,
        url=f"/data/tiles/{published.capability}/{{z}}/{{x}}/{{y}}.mvt",
        dispose_url=f"/data/layers/{published.capability}",
        expires_at=NOW + timedelta(hours=1),
        byte_count=len(SOURCE),
        min_zoom=0,
        max_zoom=18,
    )
    assert not hasattr(published, "fallback_url")


def test_manifest_failure_rolls_back_the_known_source_objects(s3_bucket) -> None:
    client, bucket = s3_bucket
    recording = RecordingS3(client, fail_manifest=True)

    assert asyncio.run(publisher(recording, bucket).publish_layer("ignored", FEATURES)) is None
    assert keys(client, bucket) == []


def test_publisher_never_reads_or_writes_backend_tombstones(s3_bucket) -> None:
    client, bucket = s3_bucket
    published = asyncio.run(publisher(client, bucket).publish_layer("ignored", FEATURES))

    assert published is not None
    assert all(not key.startswith("tombstones/") for key in keys(client, bucket))
    assert not hasattr(publisher(client, bucket), "delete_layer")


def test_queue_and_fallback_configuration_are_removed(s3_bucket) -> None:
    client, bucket = s3_bucket
    with pytest.raises(TypeError):
        publisher(client, bucket, queue_client=object(), queue_url="queue")
    with pytest.raises(TypeError):
        publisher(client, bucket, fallback_tile_base_url="/fallback")


def test_default_lifetime_is_24_hours(s3_bucket) -> None:
    client, bucket = s3_bucket
    published = asyncio.run(
        S3LayerPublisher(client, bucket, clock=lambda: NOW, source_writer=writer).publish_layer(
            "ignored", FEATURES
        )
    )
    assert published is not None
    assert published.expires_at == NOW + timedelta(hours=24)


def test_capabilities_are_random_and_logs_use_only_a_fingerprint(s3_bucket, caplog) -> None:
    client, bucket = s3_bucket
    caplog.set_level(logging.INFO)
    first = asyncio.run(publisher(client, bucket).publish_layer("secret-result", FEATURES))
    second = asyncio.run(publisher(client, bucket).publish_layer("secret-result", FEATURES))

    assert first is not None and second is not None
    assert first.capability != second.capability
    assert len(first.capability) == 43
    assert first.capability not in caplog.text
    assert capability_fingerprint(first.capability) in caplog.text
    assert "secret-result" not in caplog.text


def test_blocking_writer_and_s3_calls_leave_the_event_loop_thread(s3_bucket) -> None:
    client, bucket = s3_bucket
    recording = RecordingS3(client)
    event_loop_thread = threading.get_ident()

    asyncio.run(publisher(recording, bucket).publish_layer("ignored", FEATURES))

    assert recording.thread_ids
    assert all(thread_id != event_loop_thread for thread_id in recording.thread_ids)
