"""Deterministic GeoParquet serialization for chat-produced feature layers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pyproj import CRS
from shapely.geometry import shape  # type: ignore[import-untyped]

GEOPARQUET_VERSION = "1.1.0"
ROW_GROUP_SIZE = 64_000
_INTERNAL_COLUMNS = {"feature_id", "geometry"}


def _json_string(value: Any) -> str | None:
    """Represent a non-scalar property without losing its structure."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _property_array(values: list[Any]) -> pa.Array:
    """Keep one useful Arrow scalar type, or fall back to deterministic text."""
    present = [value for value in values if value is not None]
    if not present:
        return pa.array(values, type=pa.string())
    if all(isinstance(value, bool) for value in present):
        return pa.array(values, type=pa.bool_())
    if all(isinstance(value, int) and not isinstance(value, bool) for value in present):
        return pa.array(values, type=pa.int64())
    if all(
        isinstance(value, (int, float)) and not isinstance(value, bool)
        for value in present
    ):
        return pa.array(values, type=pa.float64())
    if all(isinstance(value, str) for value in present):
        return pa.array(values, type=pa.string())
    return pa.array([_json_string(value) for value in values], type=pa.string())


def _properties(feature: dict[str, Any]) -> dict[str, Any]:
    value = feature.get("properties")
    if not isinstance(value, dict):
        return {}
    return {str(key): item for key, item in value.items()}


def _property_columns(names: list[str]) -> dict[str, str]:
    """Assign collision-free physical columns while retaining original names."""
    occupied = set(names) | _INTERNAL_COLUMNS
    mapping: dict[str, str] = {}
    for name in names:
        if name not in _INTERNAL_COLUMNS:
            mapping[name] = name
            continue
        candidate = f"property_{name}"
        suffix = 2
        while candidate in occupied:
            candidate = f"property_{name}_{suffix}"
            suffix += 1
        occupied.add(candidate)
        mapping[name] = candidate
    return mapping


def write_geoparquet(features: list[dict[str, Any]], destination: Path) -> None:
    """Write one GeoParquet 1.1 file in OGC CRS84 longitude/latitude order."""
    if not features:
        raise ValueError("GeoParquet requires at least one feature")

    property_names = sorted(
        {key for feature in features for key in _properties(feature)}
    )
    property_columns = _property_columns(property_names)

    geometries: list[bytes] = []
    geometry_types: set[str] = set()
    minx = miny = float("inf")
    maxx = maxy = float("-inf")
    for index, feature in enumerate(features):
        geometry = feature.get("geometry")
        if not isinstance(geometry, dict):
            raise ValueError(f"feature {index} has no GeoJSON geometry")
        try:
            parsed = shape(geometry)
        except Exception as exc:
            raise ValueError(f"feature {index} has invalid GeoJSON geometry") from exc
        if parsed.is_empty:
            raise ValueError(f"feature {index} has an empty geometry")
        geometries.append(parsed.wkb)
        geometry_types.add(parsed.geom_type)
        west, south, east, north = parsed.bounds
        minx, miny = min(minx, west), min(miny, south)
        maxx, maxy = max(maxx, east), max(maxy, north)

    arrays: list[pa.Array] = [
        pa.array(
            [
                None if feature.get("id") is None else str(feature["id"])
                for feature in features
            ],
            type=pa.string(),
        ),
        pa.array(geometries, type=pa.binary()),
    ]
    columns = ["feature_id", "geometry"]
    for name in property_names:
        arrays.append(
            _property_array([_properties(feature).get(name) for feature in features])
        )
        columns.append(property_columns[name])

    table = pa.Table.from_arrays(arrays, names=columns)
    geo = {
        "version": GEOPARQUET_VERSION,
        "primary_column": "geometry",
        "columns": {
            "geometry": {
                "encoding": "WKB",
                "geometry_types": sorted(geometry_types),
                "crs": CRS.from_user_input("OGC:CRS84").to_json_dict(),
                "bbox": [minx, miny, maxx, maxy],
            }
        },
    }
    metadata = {
        **(table.schema.metadata or {}),
        b"geo": json.dumps(geo, separators=(",", ":")).encode(),
        b"sgs:property_columns": json.dumps(
            property_columns,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode(),
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(
        table.replace_schema_metadata(metadata),
        destination,
        compression="zstd",
        row_group_size=ROW_GROUP_SIZE,
    )
