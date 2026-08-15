"""GeoParquet artifact conformance tests.

The browser and external GIS tools only see these bytes, so metadata, schema, and
geometry behavior are a public contract rather than an implementation detail.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest
from shapely import from_wkb  # type: ignore[import-untyped]

from .artifacts import ROW_GROUP_SIZE, write_geoparquet
from .s3 import S3Store


FEATURES: list[dict[str, Any]] = [
    {
        "type": "Feature",
        "id": 7,
        "geometry": {"type": "Point", "coordinates": [7.44, 46.95]},
        "properties": {
            "name": "Bern",
            "lanes": 2,
            "open": True,
            "nullable": None,
            "geometry": "original property",
        },
    },
    {
        "type": "Feature",
        "id": "road-8",
        "geometry": {
            "type": "LineString",
            "coordinates": [[7.4, 46.9], [7.5, 47.0]],
        },
        "properties": {
            "name": "Aareweg",
            "lanes": 2.5,
            "tags": ["road", "walk"],
            "feature_id": "source property",
        },
    },
    {
        "type": "Feature",
        "id": None,
        "geometry": {
            "type": "MultiPolygon",
            "coordinates": [
                [[[7.41, 46.91], [7.42, 46.91], [7.42, 46.92], [7.41, 46.91]]]
            ],
        },
        "properties": {"name": "Area", "meta": {"b": 2, "a": 1}},
    },
]


def test_writes_geoparquet_11_with_wkb_crs_bbox_and_zstd(tmp_path: Any) -> None:
    output = tmp_path / "layer.parquet"

    write_geoparquet(FEATURES, output)

    table = pq.read_table(output)
    metadata = table.schema.metadata or {}
    geo = json.loads(metadata[b"geo"])
    assert geo["version"] == "1.1.0"
    assert geo["primary_column"] == "geometry"
    geometry = geo["columns"]["geometry"]
    assert geometry["encoding"] == "WKB"
    assert geometry["geometry_types"] == ["LineString", "MultiPolygon", "Point"]
    assert geometry["bbox"] == pytest.approx([7.4, 46.9, 7.5, 47.0])
    assert geometry["crs"]["id"] == {"authority": "OGC", "code": "CRS84"}
    assert table.num_rows == 3
    assert [from_wkb(value).geom_type for value in table["geometry"].to_pylist()] == [
        "Point",
        "LineString",
        "MultiPolygon",
    ]
    parquet = pq.ParquetFile(output)
    geometry_index = parquet.schema_arrow.get_field_index("geometry")
    assert parquet.metadata.row_group(0).column(geometry_index).compression == "ZSTD"


def test_preserves_ids_types_and_reserved_property_names(tmp_path: Any) -> None:
    output = tmp_path / "layer.parquet"

    write_geoparquet(FEATURES, output)

    table = pq.read_table(output)
    data = table.to_pydict()
    mapping = json.loads((table.schema.metadata or {})[b"sgs:property_columns"])
    assert data["feature_id"] == ["7", "road-8", None]
    assert data["name"] == ["Bern", "Aareweg", "Area"]
    assert data["lanes"] == [2.0, 2.5, None]
    assert data["open"] == [True, None, None]
    assert data["tags"] == [None, '["road","walk"]', None]
    assert data["meta"] == [None, None, '{"a":1,"b":2}']
    assert data[mapping["geometry"]] == ["original property", None, None]
    assert data[mapping["feature_id"]] == [None, "source property", None]
    assert mapping["name"] == "name"


def test_reserved_property_fallbacks_cannot_collide(tmp_path: Any) -> None:
    output = tmp_path / "collisions.parquet"
    feature = {
        **FEATURES[0],
        "properties": {
            "feature_id": "source id",
            "property_feature_id": "source fallback",
            "geometry": "source geometry",
            "property_geometry": "source geometry fallback",
        },
    }

    write_geoparquet([feature], output)

    table = pq.read_table(output)
    data = table.to_pydict()
    mapping = json.loads((table.schema.metadata or {})[b"sgs:property_columns"])
    assert mapping["feature_id"] == "property_feature_id_2"
    assert mapping["geometry"] == "property_geometry_2"
    assert data["feature_id"] == ["7"]
    assert data["property_feature_id"] == ["source fallback"]
    assert data["property_feature_id_2"] == ["source id"]
    assert data["property_geometry"] == ["source geometry fallback"]
    assert data["property_geometry_2"] == ["source geometry"]


def test_conflicting_property_types_become_deterministic_strings(tmp_path: Any) -> None:
    output = tmp_path / "mixed.parquet"
    features = [
        {**FEATURES[0], "properties": {"mixed": 3}},
        {**FEATURES[1], "properties": {"mixed": {"b": 2, "a": 1}}},
    ]

    write_geoparquet(features, output)

    assert pq.read_table(output)["mixed"].to_pylist() == ["3", '{"a":1,"b":2}']


def test_uses_sixty_four_thousand_row_groups(tmp_path: Any) -> None:
    output = tmp_path / "many.parquet"
    features = [
        {
            "type": "Feature",
            "id": index,
            "geometry": {
                "type": "Point",
                "coordinates": [7.0 + index / 1_000_000, 46.0],
            },
            "properties": {"index": index},
        }
        for index in range(ROW_GROUP_SIZE + 1)
    ]

    write_geoparquet(features, output)

    parquet = pq.ParquetFile(output)
    assert parquet.num_row_groups == 2
    assert parquet.metadata.row_group(0).num_rows == ROW_GROUP_SIZE
    assert parquet.metadata.row_group(1).num_rows == 1


@pytest.mark.parametrize(
    "features, message",
    [
        ([], "at least one feature"),
        ([{"type": "Feature", "properties": {}}], "has no GeoJSON geometry"),
        (
            [
                {
                    "type": "Feature",
                    "properties": {},
                    "geometry": {"type": "Point", "coordinates": []},
                }
            ],
            "empty geometry",
        ),
    ],
)
def test_refuses_unrenderable_layers(
    features: list[dict[str, Any]], message: str, tmp_path: Any
) -> None:
    with pytest.raises(ValueError, match=message):
        write_geoparquet(features, tmp_path / "invalid.parquet")


class _FakeS3:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.puts: list[dict[str, Any]] = []

    def put_object(self, **kwargs: Any) -> None:
        if self.fail:
            raise RuntimeError("upload denied: secret detail")
        self.puts.append(kwargs)

    def generate_presigned_url(
        self, operation: str, Params: dict[str, str], ExpiresIn: int
    ) -> str:
        assert operation == "get_object"
        return f"https://bucket.test/{Params['Key']}?ttl={ExpiresIn}"


def _store(client: _FakeS3) -> S3Store:
    store = S3Store.__new__(S3Store)
    store.bucket = "test-bucket"
    store.endpoint_url = None
    store.client = client
    return store


def test_publishes_geoparquet_with_media_type_and_cleans_temporary_file(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from . import s3 as module

    written: list[Path] = []
    original = write_geoparquet

    def recording_writer(features: list[dict[str, Any]], destination: Path) -> None:
        written.append(destination)
        original(features, destination)

    monkeypatch.setattr(module, "write_geoparquet", recording_writer)
    client = _FakeS3()

    url = asyncio.run(_store(client).publish_geoparquet("result.parquet", FEATURES))

    assert url == "https://bucket.test/layers/result.parquet?ttl=3600"
    assert len(client.puts) == 1
    put = client.puts[0]
    assert put["Bucket"] == "test-bucket"
    assert put["Key"] == "layers/result.parquet"
    assert put["ContentType"] == "application/vnd.apache.parquet"
    assert bytes(put["Body"][:4]) == b"PAR1"
    assert bytes(put["Body"][-4:]) == b"PAR1"
    assert written and not written[0].exists()


def test_publish_failure_returns_none_logs_and_cleans_temporary_file(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from . import s3 as module

    written: list[Path] = []
    original = write_geoparquet

    def recording_writer(features: list[dict[str, Any]], destination: Path) -> None:
        written.append(destination)
        original(features, destination)

    monkeypatch.setattr(module, "write_geoparquet", recording_writer)

    result = asyncio.run(
        _store(_FakeS3(fail=True)).publish_geoparquet("broken.parquet", FEATURES)
    )

    assert result is None
    assert "could not publish" in caplog.text
    assert written and not written[0].exists()
