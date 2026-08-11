"""Build deterministic strict WKB GeoParquet sources for real DuckDB tests."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

import pyarrow as pa
import pyarrow.parquet as pq
from shapely.geometry.base import BaseGeometry
from tile_server.model import LayerManifest


def _family(geometry: BaseGeometry) -> Literal["point", "line", "polygon"]:
    name = geometry.geom_type.lower()
    if "point" in name:
        return "point"
    if "line" in name:
        return "line"
    if "polygon" in name:
        return "polygon"
    raise AssertionError(name)


def write_geoparquet(
    path: Path,
    geometries: list[BaseGeometry | bytes],
    *,
    ids: list[int] | None = None,
    properties: dict[str, tuple[str, pa.Array]] | None = None,
    family: Literal["point", "line", "polygon"] | None = None,
    covering_column: str = "covering odd",
    covering_fields: tuple[str, str, str, str] = ("west", "south", "east", "north"),
    geo_mutation: Any | None = None,
) -> tuple[LayerManifest, dict[str, str]]:
    """Write a deterministic source with arbitrary covering/property names."""
    ids = ids or list(range(len(geometries)))
    properties = properties or {}
    valid_geometries = [item for item in geometries if isinstance(item, BaseGeometry)]
    assert valid_geometries
    family = family or _family(valid_geometries[0])
    bounds = [
        item.bounds if isinstance(item, BaseGeometry) else (90.0, 70.0, 91.0, 71.0)
        for item in geometries
    ]
    west = min(value[0] for value in bounds)
    south = min(value[1] for value in bounds)
    east = max(value[2] for value in bounds)
    north = max(value[3] for value in bounds)
    xmin, ymin, xmax, ymax = covering_fields
    covering = pa.StructArray.from_arrays(
        [
            pa.array(
                [value[index] for value in bounds],
                type=pa.float64(),
            )
            for index in range(4)
        ],
        names=[xmin, ymin, xmax, ymax],
    )
    arrays: list[pa.Array] = [
        pa.array(ids, type=pa.int64()),
        pa.array(
            [item.wkb if isinstance(item, BaseGeometry) else item for item in geometries],
            type=pa.binary(),
        ),
        covering,
    ]
    names = ["__feature_id", "geometry", covering_column]
    property_columns: dict[str, str] = {}
    for display_name, (physical_name, values) in properties.items():
        arrays.append(values)
        names.append(physical_name)
        property_columns[display_name] = physical_name
    table = pa.Table.from_arrays(arrays, names=names)
    geometry_types = sorted({item.geom_type for item in valid_geometries})
    geo: dict[str, Any] = {
        "version": "1.1.0",
        "primary_column": "geometry",
        "columns": {
            "geometry": {
                "encoding": "WKB",
                "geometry_types": geometry_types,
                "crs": {"id": {"authority": "OGC", "code": "CRS84"}},
                "bbox": [west, south, east, north],
                "covering": {
                    "bbox": {
                        "xmin": [covering_column, xmin],
                        "ymin": [covering_column, ymin],
                        "xmax": [covering_column, xmax],
                        "ymax": [covering_column, ymax],
                    }
                },
            }
        },
    }
    if geo_mutation is not None:
        geo_mutation(geo)
    table = table.replace_schema_metadata({b"geo": json.dumps(geo, separators=(",", ":")).encode()})
    pq.write_table(table, path, compression="snappy", row_group_size=2)
    persisted_schema = pq.read_schema(path)
    property_types = {
        display_name: str(persisted_schema.field(physical_name).type)
        for display_name, physical_name in property_columns.items()
    }
    encoded = path.read_bytes()
    now = datetime.now(UTC)
    manifest = LayerManifest(
        schema_version=1,
        created_at=now,
        expires_at=now + timedelta(hours=1),
        feature_count=len(geometries),
        coordinate_count=sum(len(item.wkb) for item in valid_geometries),
        complete=True,
        bbox=(west, south, east, north),
        crs="OGC:CRS84",
        geometry_type=family,
        min_zoom=0,
        fit_zoom=8,
        max_zoom=16,
        property_columns=property_columns,
        property_types=property_types,
        source_sha256=sha256(encoded).hexdigest(),
        source_bytes=len(encoded),
    )
    return manifest, property_columns
