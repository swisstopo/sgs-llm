"""Trust and deletion contract for private generated GeoParquet sources."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import boto3
import pytest
from moto import mock_aws
from tile_server.model import LayerManifest

from app.tiles.store import (
    LayerDeleteError,
    LayerExpired,
    LayerInvalid,
    LayerMissing,
    LayerStore,
    capability_fingerprint,
    validate_capability,
)

NOW = datetime(2026, 8, 11, 10, 0, tzinfo=UTC)
TOKEN = "A" * 43
SOURCE = b"PAR1-private-source-PAR1"
CHECKSUM = "1" * 64


def manifest(**changes: Any) -> LayerManifest:
    values: dict[str, Any] = {
        "schema_version": 1,
        "created_at": NOW - timedelta(minutes=1),
        "expires_at": NOW + timedelta(hours=1),
        "feature_count": 1,
        "coordinate_count": 1,
        "complete": True,
        "bbox": (7.4, 46.9, 7.5, 47.0),
        "crs": "OGC:CRS84",
        "geometry_type": "point",
        "min_zoom": 0,
        "fit_zoom": 1,
        "max_zoom": 2,
        "property_columns": {"name": "name"},
        "property_types": {"name": "string"},
        "source_sha256": CHECKSUM,
        "source_bytes": len(SOURCE),
    }
    values.update(changes)
    return LayerManifest(**values)


@pytest.fixture
def s3_bucket():
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket="generated-layers-test")
        yield client, "generated-layers-test"


def store(client: Any, bucket: str, **kwargs: Any) -> LayerStore:
    return LayerStore(client, bucket, clock=lambda: NOW, **kwargs)


def put_layer(client: Any, bucket: str, current: LayerManifest | None = None) -> LayerManifest:
    value = current or manifest()
    client.put_object(
        Bucket=bucket,
        Key=f"layers/{TOKEN}/source.parquet",
        Body=SOURCE,
        Metadata={
            "source-sha256": value.source_sha256,
            "source-bytes": str(value.source_bytes),
        },
    )
    client.put_object(
        Bucket=bucket,
        Key=f"layers/{TOKEN}/manifest.json",
        Body=value.to_json(),
    )
    return value


@pytest.mark.parametrize("value", ["", "A" * 42, "A" * 44, "?" * 43])
def test_capability_is_strict(value: str) -> None:
    with pytest.raises(ValueError):
        validate_capability(value)


def test_manifest_is_the_commit_marker(s3_bucket) -> None:
    client, bucket = s3_bucket
    current = manifest()
    client.put_object(
        Bucket=bucket,
        Key=f"layers/{TOKEN}/source.parquet",
        Body=SOURCE,
        Metadata={"source-sha256": CHECKSUM, "source-bytes": str(len(SOURCE))},
    )
    layer_store = store(client, bucket)

    with pytest.raises(LayerMissing):
        layer_store.manifest(TOKEN)
    client.put_object(Bucket=bucket, Key=f"layers/{TOKEN}/manifest.json", Body=current.to_json())
    assert layer_store.manifest(TOKEN) == current


def test_tombstone_and_expiry_are_authoritative(s3_bucket) -> None:
    client, bucket = s3_bucket
    put_layer(client, bucket)
    client.put_object(Bucket=bucket, Key=f"tombstones/{TOKEN}", Body=b"deleted")
    with pytest.raises(LayerMissing):
        store(client, bucket).manifest(TOKEN)

    client.delete_object(Bucket=bucket, Key=f"tombstones/{TOKEN}")
    put_layer(client, bucket, manifest(expires_at=NOW))
    with pytest.raises(LayerExpired):
        store(client, bucket).manifest(TOKEN)


@pytest.mark.parametrize("body", [b"not-json", b"{}", b" " * 1025])
def test_manifest_parser_and_byte_ceiling_are_strict(s3_bucket, body: bytes) -> None:
    client, bucket = s3_bucket
    client.put_object(Bucket=bucket, Key=f"layers/{TOKEN}/manifest.json", Body=body)
    with pytest.raises(LayerInvalid):
        store(client, bucket, manifest_max_bytes=1024).manifest(TOKEN)


@pytest.mark.parametrize(
    "metadata",
    [
        {"source-sha256": "2" * 64, "source-bytes": str(len(SOURCE))},
        {"source-sha256": CHECKSUM, "source-bytes": "1"},
        {"source-sha256": CHECKSUM},
        {"source-bytes": str(len(SOURCE))},
    ],
)
def test_source_ref_requires_exact_size_and_publisher_metadata(
    s3_bucket, metadata: dict[str, str]
) -> None:
    client, bucket = s3_bucket
    current = manifest()
    client.put_object(
        Bucket=bucket,
        Key=f"layers/{TOKEN}/source.parquet",
        Body=SOURCE,
        Metadata=metadata,
    )
    with pytest.raises(LayerInvalid):
        store(client, bucket).source_ref(TOKEN, current)


def test_source_ref_is_a_private_task_role_uri(s3_bucket) -> None:
    client, bucket = s3_bucket
    current = put_layer(client, bucket)
    source = store(client, bucket).source_ref(TOKEN, current)

    assert source.uri == f"s3://{bucket}/layers/{TOKEN}/source.parquet"
    assert repr(source) == "SourceRef(<private>)"


def test_delete_tombstones_then_removes_only_the_two_source_objects(s3_bucket) -> None:
    client, bucket = s3_bucket
    put_layer(client, bucket)
    client.put_object(Bucket=bucket, Key=f"unrelated/{TOKEN}", Body=b"keep")
    layer_store = store(client, bucket)

    layer_store.delete(TOKEN)
    layer_store.delete(TOKEN)

    response = client.list_objects_v2(Bucket=bucket)
    keys = {item["Key"] for item in response.get("Contents", [])}
    assert keys == {f"tombstones/{TOKEN}", f"unrelated/{TOKEN}"}
    with pytest.raises(LayerMissing):
        layer_store.manifest(TOKEN)


def test_delete_errors_are_redacted_and_keep_the_tombstone() -> None:
    class FailingDelete:
        def __init__(self) -> None:
            self.tombstoned = False

        def put_object(self, **kwargs: Any) -> None:
            self.tombstoned = kwargs["Key"] == f"tombstones/{TOKEN}"

        def delete_objects(self, **_kwargs: Any) -> dict[str, Any]:
            return {"Errors": [{"Key": f"layers/{TOKEN}/source.parquet", "Code": "Denied"}]}

    client = FailingDelete()
    with pytest.raises(LayerDeleteError) as caught:
        store(client, "bucket").delete(TOKEN)
    assert client.tombstoned
    assert TOKEN not in str(caught.value)
    assert capability_fingerprint(TOKEN) in str(caught.value)


def test_store_has_no_shared_tile_persistence_api(s3_bucket) -> None:
    client, bucket = s3_bucket
    layer_store = store(client, bucket)
    assert not hasattr(layer_store, "get_tile")
    assert not hasattr(layer_store, "put_tile")
