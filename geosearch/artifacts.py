"""Build the private, durable GeoParquet source for one MVT layer."""

from __future__ import annotations

import json
import math
import os
import random
import subprocess
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

import duckdb
import numpy as np
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pyproj import CRS, Transformer
from shapely import from_wkb, get_coordinates, get_num_coordinates
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import transform

from tile_server.model import LayerManifest


GEOPARQUET_VERSION = "1.1.0"
ROW_GROUP_SIZE = 10_000
MAX_SOURCE_BYTES = 256 * 1024 * 1024
_CRS = "OGC:CRS84"
_GEOMETRY_COLUMN = "geometry"
_FEATURE_ID_COLUMN = "__feature_id"
_RESERVED_COLUMNS = frozenset({_GEOMETRY_COLUMN, _FEATURE_ID_COLUMN, "bbox"})
_HARD_MAX_ZOOM = 16
_TILE_BUDGET = 4096
_WEBMERCATOR_RESOLUTION_Z0 = 156543.03392804097
_ZOOM_SAMPLE_SIZE = 50_000
_ZOOM_VERTEX_BUDGET = 500_000
_POINT_MAX_PER_TILE = 6000
_POINT_TILE_TARGET_BYTES = 500_000
_POINT_GRID_PX = 1.5
_MVT_EXTENT = 4096.0
_SIMPLIFY_PX = 0.5


class ArtifactTooLarge(ValueError):
    """The validated source exceeds the bounded artifact size."""


class SourceValidationError(ValueError):
    """OGR returned a Parquet file that does not satisfy the source contract."""


class OgrConversionError(RuntimeError):
    """The pinned OGR conversion failed without producing a usable source."""


@dataclass(frozen=True, slots=True)
class SourceArtifact:
    path: Path
    byte_count: int
    checksum: str
    manifest: LayerManifest


@dataclass(frozen=True, slots=True)
class _PreparedSource:
    features: list[dict[str, Any]]
    geometries: list[BaseGeometry]
    geometry_family: Literal["point", "line", "polygon"]
    bbox: tuple[float, float, float, float]
    coordinate_count: int
    property_columns: dict[str, str]
    property_arrays: dict[str, pa.Array]


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _json_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _property_array(values: list[Any]) -> pa.Array:
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
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError("feature properties must be an object")
    properties: dict[str, Any] = {}
    for key, item in value.items():
        name = str(key)
        if name in properties:
            raise ValueError(
                f"property names collide after string conversion: {name!r}"
            )
        properties[name] = item
    return properties


def _escape_property_name(name: str) -> str:
    escaped = "".join(
        chr(byte)
        if 48 <= byte <= 57 or 65 <= byte <= 90 or 97 <= byte <= 122
        else f"_{byte:02x}"
        for byte in name.encode("utf-8")
    )
    return escaped or "property"


def _property_column_map(property_names: list[str]) -> dict[str, str]:
    used = set(_RESERVED_COLUMNS)
    mapping: dict[str, str] = {}
    for name in sorted(property_names):
        base = _escape_property_name(name)
        candidate = base
        if candidate in used or candidate.startswith("__sgs_"):
            digest = sha256(name.encode("utf-8")).hexdigest()
            length = 12
            candidate = f"{base}x{digest[:length]}"
            while candidate in used or candidate.startswith("__sgs_"):
                length += 4
                candidate = f"{base}x{digest[:length]}"
        mapping[name] = candidate
        used.add(candidate)
    return mapping


def _deduplicate(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduplicated: list[dict[str, Any]] = []
    seen: set[tuple[type[object], object]] = set()
    for index, feature in enumerate(features):
        if not isinstance(feature, dict):
            raise ValueError(f"feature {index} must be an object")
        public_id = feature.get("id")
        if public_id is not None:
            if isinstance(public_id, bool) or not isinstance(
                public_id, (int, float, str)
            ):
                raise ValueError(f"feature {index} id must be a string or number")
            if isinstance(public_id, float) and not math.isfinite(public_id):
                raise ValueError(f"feature {index} id must be finite")
            marker: tuple[type[object], object] = (type(public_id), public_id)
            if marker in seen:
                continue
            seen.add(marker)
        deduplicated.append(feature)
    return deduplicated


def _geometry_family(geometry: BaseGeometry) -> Literal["point", "line", "polygon"]:
    kind = geometry.geom_type.lower()
    if "point" in kind:
        return "point"
    if "line" in kind:
        return "line"
    if "polygon" in kind:
        return "polygon"
    raise ValueError(f"unsupported GeoJSON geometry type: {geometry.geom_type}")


def _coordinate_count(value: Any) -> int:
    if not isinstance(value, list) or not value:
        return 0
    if isinstance(value[0], (int, float)) and not isinstance(value[0], bool):
        return 1
    return sum(_coordinate_count(child) for child in value)


def _prepare(features: list[dict[str, Any]]) -> _PreparedSource:
    if not features:
        raise ValueError("GeoParquet requires at least one feature")
    deduplicated = _deduplicate(features)
    if not deduplicated:
        raise ValueError("GeoParquet requires at least one feature after deduplication")

    property_rows = [_properties(feature) for feature in deduplicated]
    property_names = sorted({name for row in property_rows for name in row})
    property_columns = _property_column_map(property_names)
    property_arrays = {
        name: _property_array([row.get(name) for row in property_rows])
        for name in property_names
    }

    geometries: list[BaseGeometry] = []
    families: set[Literal["point", "line", "polygon"]] = set()
    coordinate_count = 0
    minx = miny = float("inf")
    maxx = maxy = float("-inf")
    for index, feature in enumerate(deduplicated):
        geometry_value = feature.get("geometry")
        if not isinstance(geometry_value, dict):
            raise ValueError(f"feature {index} has no GeoJSON geometry")
        try:
            geometry = shape(geometry_value)
        except Exception as exc:
            raise ValueError(f"feature {index} has invalid GeoJSON geometry") from exc
        if geometry.is_empty:
            raise ValueError(f"feature {index} has an empty geometry")
        bounds = geometry.bounds
        if len(bounds) != 4 or not all(math.isfinite(value) for value in bounds):
            raise ValueError(f"feature {index} has invalid GeoJSON geometry bounds")
        geometries.append(geometry)
        families.add(_geometry_family(geometry))
        west, south, east, north = bounds
        minx, miny = min(minx, west), min(miny, south)
        maxx, maxy = max(maxx, east), max(maxy, north)
        coordinate_count += _coordinate_count(geometry_value.get("coordinates"))
    if len(families) != 1:
        raise ValueError("a source must contain exactly one geometry family")

    return _PreparedSource(
        features=deduplicated,
        geometries=geometries,
        geometry_family=next(iter(families)),
        bbox=(minx, miny, maxx, maxy),
        coordinate_count=coordinate_count,
        property_columns=property_columns,
        property_arrays=property_arrays,
    )


def _write_standard_source(prepared: _PreparedSource, path: Path) -> pa.Table:
    arrays: list[pa.Array] = [
        pa.array(range(len(prepared.features)), type=pa.int64()),
        pa.array([geometry.wkb for geometry in prepared.geometries], type=pa.binary()),
    ]
    names = [_FEATURE_ID_COLUMN, _GEOMETRY_COLUMN]
    for property_name, physical_name in prepared.property_columns.items():
        arrays.append(prepared.property_arrays[property_name])
        names.append(physical_name)
    table = pa.Table.from_arrays(arrays, names=names)
    geo = {
        "version": GEOPARQUET_VERSION,
        "primary_column": _GEOMETRY_COLUMN,
        "columns": {
            _GEOMETRY_COLUMN: {
                "encoding": "WKB",
                "geometry_types": sorted(
                    {geometry.geom_type for geometry in prepared.geometries}
                ),
                "crs": CRS.from_user_input(_CRS).to_json_dict(),
                "bbox": list(prepared.bbox),
            }
        },
    }
    metadata = {
        **(table.schema.metadata or {}),
        b"geo": json.dumps(geo, separators=(",", ":")).encode("utf-8"),
        b"sgs:property_columns": json.dumps(
            prepared.property_columns,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8"),
    }
    table = table.replace_schema_metadata(metadata)
    pq.write_table(table, path, compression="snappy", row_group_size=ROW_GROUP_SIZE)
    return table


def _ogr_command(output: Path, source: Path) -> list[str]:
    return [
        "ogr2ogr",
        "-f",
        "Parquet",
        str(output),
        str(source),
        "-lco",
        "COMPRESSION=SNAPPY",
        "-lco",
        f"ROW_GROUP_SIZE={ROW_GROUP_SIZE}",
        "-lco",
        "GEOMETRY_ENCODING=WKB",
        "-lco",
        "SORT_BY_BBOX=YES",
        "-lco",
        "WRITE_COVERING_BBOX=YES",
        "-nlt",
        "PROMOTE_TO_MULTI",
    ]


def _run_ogr2ogr(command: list[str], env: dict[str, str]) -> None:
    result = subprocess.run(
        command, capture_output=True, text=True, env=env, check=False
    )
    if result.returncode != 0:
        detail = (
            result.stderr.strip() or result.stdout.strip() or "no diagnostic output"
        )
        raise OgrConversionError(
            f"ogr2ogr conversion failed ({result.returncode}): {detail}"
        )


def _covering(
    geometry_metadata: dict[str, Any], table: pa.Table
) -> tuple[str, dict[str, str]]:
    covering = geometry_metadata.get("covering")
    bbox = covering.get("bbox") if isinstance(covering, dict) else None
    if not isinstance(bbox, dict) or set(bbox) != {"xmin", "ymin", "xmax", "ymax"}:
        raise SourceValidationError("GeoParquet geometry metadata has no covering bbox")
    column: str | None = None
    fields: dict[str, str] = {}
    for logical in ("xmin", "ymin", "xmax", "ymax"):
        path = bbox.get(logical)
        if (
            not isinstance(path, list)
            or len(path) != 2
            or not all(isinstance(item, str) and item for item in path)
        ):
            raise SourceValidationError(
                "GeoParquet covering paths must have column and field"
            )
        if column is None:
            column = path[0]
        elif path[0] != column:
            raise SourceValidationError(
                "GeoParquet covering paths must share one struct column"
            )
        fields[logical] = path[1]
    if column is None or column not in table.column_names:
        raise SourceValidationError("GeoParquet covering struct column is absent")
    field = table.schema.field(column)
    if not pa.types.is_struct(field.type):
        raise SourceValidationError("GeoParquet covering column must be a struct")
    available = {child.name for child in field.type}
    if not set(fields.values()) <= available:
        raise SourceValidationError("GeoParquet covering struct fields are absent")
    if any(
        not pa.types.is_floating(field.type.field(name).type)
        for name in fields.values()
    ):
        raise SourceValidationError("GeoParquet covering fields must be floating point")
    return column, fields


def _covering_value_is_valid(
    actual: float,
    expected: float,
    field_type: pa.DataType,
    *,
    minimum: bool,
) -> bool:
    if not math.isfinite(actual):
        return False
    if pa.types.is_float32(field_type):
        tolerance = max(abs(expected), 1.0) * 2**-22
    else:
        tolerance = max(abs(expected), 1.0) * 2**-51
    contains = actual <= expected if minimum else actual >= expected
    return contains and abs(actual - expected) <= tolerance


def _validated_dataset_bbox(
    value: object,
    expected: tuple[float, float, float, float],
) -> tuple[float, float, float, float]:
    if (
        not isinstance(value, list)
        or len(value) != 4
        or any(
            type(item) not in (int, float) or not math.isfinite(item) for item in value
        )
    ):
        raise SourceValidationError("source GeoParquet dataset bbox is invalid")
    bbox = (float(value[0]), float(value[1]), float(value[2]), float(value[3]))
    if not all(
        _covering_value_is_valid(
            actual,
            exact,
            pa.float64(),
            minimum=index < 2,
        )
        for index, (actual, exact) in enumerate(zip(bbox, expected, strict=True))
    ):
        raise SourceValidationError(
            "source GeoParquet dataset bbox does not match the source"
        )
    return bbox


def _validate_source(
    path: Path,
    prepared: _PreparedSource,
    standard: pa.Table,
) -> tuple[pa.Table, dict[str, str]]:
    if not path.is_file():
        raise SourceValidationError("ogr2ogr did not produce a source file")
    try:
        table = pq.read_table(path)
        file_metadata = pq.read_metadata(path).metadata or {}
    except Exception as exc:
        raise SourceValidationError("source is not readable Parquet") from exc
    expected_count = len(prepared.features)
    if table.num_rows != expected_count:
        raise SourceValidationError(
            f"source row count is {table.num_rows}, expected {expected_count}"
        )
    if (
        _FEATURE_ID_COLUMN not in table.column_names
        or table[_FEATURE_ID_COLUMN].type != pa.int64()
    ):
        raise SourceValidationError("source __feature_id must be signed int64")
    ids = table[_FEATURE_ID_COLUMN].to_pylist()
    if len(set(ids)) != expected_count or set(ids) != set(range(expected_count)):
        raise SourceValidationError(
            "source __feature_id values are not unique and deterministic"
        )

    try:
        geo = json.loads(file_metadata[b"geo"])
        geometry_metadata = geo["columns"][_GEOMETRY_COLUMN]
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SourceValidationError(
            "source has no valid GeoParquet geo metadata"
        ) from exc
    if not isinstance(geometry_metadata, dict):
        raise SourceValidationError("source has no valid GeoParquet geo metadata")
    if geo.get("version") != GEOPARQUET_VERSION:
        raise SourceValidationError("source GeoParquet version must be 1.1.0")
    if geo.get("primary_column") != _GEOMETRY_COLUMN:
        raise SourceValidationError("source primary geometry column is invalid")
    if geometry_metadata.get("encoding") != "WKB":
        raise SourceValidationError("source geometry encoding must be WKB")
    if "crs" in geometry_metadata:
        crs_metadata = geometry_metadata["crs"]
        if not isinstance(crs_metadata, dict):
            raise SourceValidationError("source geometry CRS metadata is invalid")
        try:
            source_crs = CRS.from_json_dict(crs_metadata)
        except Exception as exc:
            raise SourceValidationError(
                "source geometry CRS metadata is invalid"
            ) from exc
        if source_crs != CRS.from_user_input(_CRS):
            raise SourceValidationError("source geometry CRS is not OGC:CRS84")
    _validated_dataset_bbox(geometry_metadata.get("bbox"), prepared.bbox)
    if _GEOMETRY_COLUMN not in table.column_names or not (
        pa.types.is_binary(table[_GEOMETRY_COLUMN].type)
        or pa.types.is_large_binary(table[_GEOMETRY_COLUMN].type)
    ):
        raise SourceValidationError("source WKB geometry column must be binary")
    covering_column, covering_fields = _covering(geometry_metadata, table)

    expected_columns = {
        _FEATURE_ID_COLUMN,
        _GEOMETRY_COLUMN,
        covering_column,
        *prepared.property_columns.values(),
    }
    if set(table.column_names) != expected_columns:
        raise SourceValidationError("source columns do not match the property mapping")

    expected_rows = standard.to_pydict()
    actual_rows = table.to_pydict()
    actual_indexes = {feature_id: index for index, feature_id in enumerate(ids)}
    for property_name, physical_name in prepared.property_columns.items():
        del property_name
        for feature_id in range(expected_count):
            if (
                actual_rows[physical_name][actual_indexes[feature_id]]
                != expected_rows[physical_name][feature_id]
            ):
                raise SourceValidationError(
                    f"source property values changed for {physical_name!r}"
                )

    geometry_types: set[str] = set()
    covering_values = actual_rows[covering_column]
    for row_index, value in enumerate(actual_rows[_GEOMETRY_COLUMN]):
        try:
            geometry = from_wkb(value)
        except Exception as exc:
            raise SourceValidationError("source contains invalid WKB geometry") from exc
        if geometry.is_empty or _geometry_family(geometry) != prepared.geometry_family:
            raise SourceValidationError("source WKB geometry family is invalid")
        if not geometry.geom_type.startswith("Multi"):
            raise SourceValidationError(
                "source geometry was not promoted to multi geometry"
            )
        feature_id = ids[row_index]
        expected_geometry = prepared.geometries[feature_id]
        if not geometry.equals(expected_geometry):
            raise SourceValidationError(
                "source geometry does not match its internal feature ID"
            )
        geometry_types.add(geometry.geom_type)
        row_bbox = covering_values[row_index]
        if not isinstance(row_bbox, dict):
            raise SourceValidationError("source covering struct has invalid values")
        raw_bbox = tuple(
            row_bbox[covering_fields[name]] for name in ("xmin", "ymin", "xmax", "ymax")
        )
        if any(
            type(item) not in (int, float) or not math.isfinite(item)
            for item in raw_bbox
        ):
            raise SourceValidationError("source covering bbox has invalid values")
        actual_bbox = tuple(float(item) for item in raw_bbox)
        covering_type = table.schema.field(covering_column).type
        field_types = tuple(
            covering_type.field(covering_fields[name]).type
            for name in ("xmin", "ymin", "xmax", "ymax")
        )
        if not all(
            _covering_value_is_valid(
                actual,
                expected,
                field_type,
                minimum=index < 2,
            )
            for index, (actual, expected, field_type) in enumerate(
                zip(actual_bbox, geometry.bounds, field_types, strict=True)
            )
        ):
            raise SourceValidationError(
                "source covering bbox does not match WKB geometry"
            )
    declared_types = geometry_metadata.get("geometry_types")
    if not isinstance(declared_types, list) or set(declared_types) != geometry_types:
        raise SourceValidationError("source GeoParquet geometry types do not match WKB")

    try:
        connection = duckdb.connect()
        try:
            duckdb_count = connection.execute(
                "SELECT count(*) FROM read_parquet(?)", [str(path)]
            ).fetchone()
            described = connection.execute(
                "DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]
            ).fetchall()
        finally:
            connection.close()
    except Exception as exc:
        raise SourceValidationError("DuckDB cannot read the source") from exc
    if duckdb_count is None or duckdb_count[0] != expected_count:
        raise SourceValidationError("DuckDB source row count is invalid")
    duckdb_types = {row[0]: str(row[1]).upper() for row in described}
    duckdb_geometry_type = duckdb_types.get(_GEOMETRY_COLUMN, "")
    if duckdb_types.get(_FEATURE_ID_COLUMN) != "BIGINT" or not (
        duckdb_geometry_type == "BLOB" or duckdb_geometry_type.startswith("GEOMETRY")
    ):
        raise SourceValidationError("DuckDB source ID or WKB type is invalid")

    property_types = {
        original: str(table.schema.field(physical).type)
        for original, physical in prepared.property_columns.items()
    }
    return table, property_types


def _bbox_tile_range(
    bbox: tuple[float, float, float, float], zoom: int
) -> tuple[range, range]:
    west, south, east, north = bbox
    count = 1 << zoom

    def tile_x(longitude: float) -> int:
        candidate = int((longitude + 180.0) / 360.0 * count)
        if candidate < 0:
            return 0
        if candidate >= count:
            return count - 1
        return candidate

    def tile_y(latitude: float) -> int:
        latitude = max(-85.05112878, min(85.05112878, latitude))
        mercator = math.asinh(math.tan(math.radians(latitude)))
        candidate = int((1.0 - mercator / math.pi) / 2.0 * count)
        if candidate < 0:
            return 0
        if candidate >= count:
            return count - 1
        return candidate

    x0, x1 = sorted((tile_x(west), tile_x(east)))
    y0, y1 = sorted((tile_y(north), tile_y(south)))
    return range(x0, x1 + 1), range(y0, y1 + 1)


def _count_points_in_tiles(
    longitude: np.ndarray, latitude: np.ndarray, zoom: int
) -> int:
    if longitude.size == 0:
        return 0
    count = 2**zoom
    tile_x = np.clip(
        ((longitude + 180.0) / 360.0 * count).astype(np.int64), 0, count - 1
    )
    latitude = np.clip(latitude, -85.05112878, 85.05112878)
    mercator = np.arcsinh(np.tan(np.radians(latitude)))
    tile_y = np.clip(
        ((1.0 - mercator / np.pi) / 2.0 * count).astype(np.int64),
        0,
        count - 1,
    )
    keys = tile_x * count + tile_y
    counts = np.unique(keys, return_counts=True)[1]
    return int(counts.max()) if counts.size else 0


def _find_point_max_zoom(
    longitude: np.ndarray,
    latitude: np.ndarray,
    maximum_density: int,
    extent_cap: int,
    *,
    extra_zoom: int = 0,
) -> int:
    for zoom in range(1, extent_cap + 1):
        probe_zoom = min(zoom + extra_zoom, 28)
        if _count_points_in_tiles(longitude, latitude, probe_zoom) <= maximum_density:
            return zoom
    return extent_cap


def _point_grid_cell() -> float:
    pixel_grid = max(1.0, _POINT_GRID_PX * _MVT_EXTENT / 256.0)
    density_grid = _MVT_EXTENT / math.sqrt(_POINT_MAX_PER_TILE)
    return max(pixel_grid, density_grid)


def _point_max_zoom(
    longitude: np.ndarray,
    latitude: np.ndarray,
    *,
    attribute_count: int,
    extent_cap: int,
) -> int:
    estimated_bytes_per_point = 24 + max(0, attribute_count) * 6
    byte_cap = _POINT_TILE_TARGET_BYTES // estimated_bytes_per_point
    maximum_points = max(500, min(_POINT_MAX_PER_TILE, byte_cap))
    count_zoom = _find_point_max_zoom(longitude, latitude, maximum_points, extent_cap)
    cell_extra = max(0, int(math.ceil(math.log2(_MVT_EXTENT / _point_grid_cell()))))
    spacing_zoom = _find_point_max_zoom(
        longitude,
        latitude,
        1,
        extent_cap,
        extra_zoom=cell_extra,
    )
    return max(count_zoom, spacing_zoom)


def _zoom_sample_indexes(
    feature_count: int, total_coordinate_count: int
) -> Sequence[int]:
    if (
        feature_count <= _ZOOM_SAMPLE_SIZE
        and total_coordinate_count <= _ZOOM_VERTEX_BUDGET
    ):
        return range(feature_count)
    fraction = (
        _ZOOM_VERTEX_BUDGET / total_coordinate_count
        if total_coordinate_count > _ZOOM_VERTEX_BUDGET
        else 1.0
    )
    sample_count = min(
        feature_count,
        max(50, min(_ZOOM_SAMPLE_SIZE, int(feature_count * fraction))),
    )
    return random.Random(42).sample(range(feature_count), sample_count)


def _projected_average_edge_length(geometries: Sequence[BaseGeometry]) -> float:
    project = Transformer.from_crs(_CRS, "EPSG:3857", always_xy=True).transform
    total_length = 0.0
    total_coordinates = 0
    for geometry in geometries:
        total_length += transform(project, geometry).length
        total_coordinates += int(get_num_coordinates(geometry))
    return total_length / total_coordinates if total_coordinates else 0.0


def _find_simplify_max_zoom(average_edge_metres: float, extent_cap: int) -> int:
    if average_edge_metres <= 0:
        return extent_cap
    for zoom in range(1, extent_cap + 1):
        tolerance = _SIMPLIFY_PX * _WEBMERCATOR_RESOLUTION_Z0 / (2**zoom)
        if tolerance <= average_edge_metres:
            return zoom
    return extent_cap


def _line_polygon_max_zoom(
    geometries: Sequence[BaseGeometry],
    *,
    total_coordinate_count: int,
    extent_cap: int,
) -> int:
    indexes = _zoom_sample_indexes(len(geometries), total_coordinate_count)
    working = [geometries[index] for index in indexes]
    average_edge = _projected_average_edge_length(working)
    return _find_simplify_max_zoom(average_edge, extent_cap)


def _zoom_range(prepared: _PreparedSource) -> tuple[int, int, int]:
    extent_cap = 0
    for zoom in range(_HARD_MAX_ZOOM, 0, -1):
        xs, ys = _bbox_tile_range(prepared.bbox, zoom)
        if len(xs) * len(ys) <= _TILE_BUDGET:
            extent_cap = zoom
            break
    fit_zoom = 0
    for zoom in range(extent_cap, 0, -1):
        xs, ys = _bbox_tile_range(prepared.bbox, zoom)
        if len(xs) <= 2 and len(ys) <= 2:
            fit_zoom = zoom
            break
    if prepared.geometry_family == "point":
        coordinates = get_coordinates(np.asarray(prepared.geometries, dtype=object))
        if coordinates.shape[0] == 0:
            raise ValueError("point source contains no coordinates")
        detail_zoom = _point_max_zoom(
            coordinates[:, 0],
            coordinates[:, 1],
            attribute_count=len(prepared.property_columns),
            extent_cap=extent_cap,
        )
    else:
        detail_zoom = _line_polygon_max_zoom(
            prepared.geometries,
            total_coordinate_count=prepared.coordinate_count,
            extent_cap=extent_cap,
        )
    max_zoom = max(fit_zoom, min(detail_zoom, extent_cap))
    return 0, fit_zoom, max_zoom


def write_source(
    features: list[dict[str, Any]],
    path: Path,
    *,
    expires_at: datetime,
    complete: bool,
) -> SourceArtifact:
    """Write and validate one collision-safe spatially ordered GeoParquet source."""
    if (
        not isinstance(expires_at, datetime)
        or expires_at.tzinfo is None
        or expires_at.utcoffset() != UTC.utcoffset(expires_at)
    ):
        raise ValueError("expires_at must be a UTC datetime")
    if type(complete) is not bool:
        raise ValueError("complete must be a boolean")
    path = Path(path)
    if path.exists():
        raise FileExistsError(path)
    prepared = _prepare(features)
    path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(
        prefix="sgs-source-", dir=path.parent
    ) as directory:
        private = Path(directory)
        standard_path = private / "standard.parquet"
        converted_path = private / "converted.parquet"
        standard = _write_standard_source(prepared, standard_path)
        environment = dict(os.environ)
        environment["OGR2OGR_USE_ARROW_API"] = "YES"
        _run_ogr2ogr(_ogr_command(converted_path, standard_path), environment)
        _, property_types = _validate_source(converted_path, prepared, standard)

        source_bytes = converted_path.stat().st_size
        if source_bytes > MAX_SOURCE_BYTES:
            unit = "byte" if MAX_SOURCE_BYTES == 1 else "bytes"
            raise ArtifactTooLarge(
                f"GeoParquet source is {source_bytes} bytes; maximum is {MAX_SOURCE_BYTES} {unit}"
            )
        checksum = _file_sha256(converted_path)
        min_zoom, fit_zoom, max_zoom = _zoom_range(prepared)
        manifest = LayerManifest(
            schema_version=1,
            created_at=datetime.now(UTC),
            expires_at=expires_at,
            feature_count=len(prepared.features),
            coordinate_count=prepared.coordinate_count,
            complete=complete,
            bbox=prepared.bbox,
            crs=_CRS,
            geometry_type=prepared.geometry_family,
            min_zoom=min_zoom,
            fit_zoom=fit_zoom,
            max_zoom=max_zoom,
            property_columns=prepared.property_columns,
            property_types=property_types,
            source_sha256=checksum,
            source_bytes=source_bytes,
        )
        os.replace(converted_path, path)
    return SourceArtifact(
        path=path, byte_count=source_bytes, checksum=checksum, manifest=manifest
    )
