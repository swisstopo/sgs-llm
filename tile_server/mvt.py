"""One isolated, bounded GeoParquet-to-MVT render derived from PublicForge."""

from __future__ import annotations

import contextlib
import json
import math
import re
import shutil
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

import duckdb

from .model import (
    LayerManifest,
    RenderLimits,
    RenderTimedOut,
    SourceInvalid,
    SourceRef,
    TileCoord,
    TileTooLarge,
)

MVT_EXTENT = 4096
MVT_BUFFER = 256
SIMPLIFY_PIXELS = 0.5
POINT_GRID_PIXELS = 1.5
WEBMERCATOR_RESOLUTION_Z0 = 156543.03392804097

_FAMILY_CODE: dict[str, int] = {"point": 1, "line": 2, "polygon": 3}
_FAMILY_DIMENSION: dict[str, int] = {"point": 0, "line": 1, "polygon": 2}
_GEOPARQUET_GEOMETRY_FAMILY = {
    "Point": "point",
    "Point Z": "point",
    "MultiPoint": "point",
    "MultiPoint Z": "point",
    "LineString": "line",
    "LineString Z": "line",
    "MultiLineString": "line",
    "MultiLineString Z": "line",
    "Polygon": "polygon",
    "Polygon Z": "polygon",
    "MultiPolygon": "polygon",
    "MultiPolygon Z": "polygon",
}


@dataclass(frozen=True, slots=True)
class _ParquetLogicalContract:
    physical_type: str
    converted_type: str | None
    logical_type: str


@dataclass(frozen=True, slots=True)
class _PropertyContract:
    duckdb_type: str
    mvt_type: str
    parquet: _ParquetLogicalContract | None = None


@dataclass(frozen=True, slots=True)
class _ParquetField:
    physical_type: str | None
    converted_type: str | None
    logical_type: str | None


@dataclass(frozen=True, slots=True)
class _SourceSchema:
    geometry_column: str
    geometry_is_blob: bool
    covering_column: str
    covering_fields: dict[str, str]
    properties: tuple[tuple[str, str, str], ...]
    family: Literal["point", "line", "polygon"]


def _internal_aliases(schema: _SourceSchema) -> tuple[str, str]:
    used = {display for display, _, _ in schema.properties}

    def allocate(base: str) -> str:
        candidate = base
        while candidate in used:
            candidate += "_"
        used.add(candidate)
        return candidate

    return allocate("__sgs_mvt_geometry"), allocate("__sgs_mvt_feature_id")


def _new_connection() -> duckdb.DuckDBPyConnection:
    return duckdb.connect(database=":memory:")


def _quote_literal(value: object) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _configure_connection(
    connection: Any,
    source: SourceRef,
    limits: RenderLimits,
    spill: Path,
    timed_out: threading.Event,
) -> None:
    def execute(statement: str) -> None:
        _check_deadline(timed_out)
        connection.execute(statement)
        _check_deadline(timed_out)

    execute("SET autoinstall_known_extensions = false")
    execute("SET autoload_known_extensions = false")
    if limits.extension_directory is not None:
        execute(f"SET extension_directory = {_quote_literal(limits.extension_directory)}")
    execute("SET threads = 1")
    execute("SET TimeZone = 'UTC'")
    execute(f"SET memory_limit = '{limits.memory_bytes}B'")
    execute(f"SET temp_directory = {_quote_literal(spill)}")
    execute(f"SET max_temp_directory_size = '{limits.max_spill_bytes}B'")
    execute("SET preserve_insertion_order = false")
    execute("LOAD spatial")
    # Keep the physical WKB column as BLOB. This makes the four-edge covering
    # predicate run before the explicit ST_GeomFromWKB expression.
    execute("SET enable_geoparquet_conversion = false")
    if source.is_s3:
        execute("LOAD httpfs")
        execute("LOAD aws")
        secret = "TYPE s3, PROVIDER credential_chain"
        if limits.s3_endpoint_url is not None:
            endpoint = urlsplit(limits.s3_endpoint_url)
            secret += (
                f", ENDPOINT {_quote_literal(endpoint.netloc)}, "
                f"USE_SSL {str(endpoint.scheme == 'https').lower()}, URL_STYLE path"
            )
        execute(f"CREATE SECRET sgs_mvt_source ({secret})")


def _read_geo_metadata(connection: Any, source: SourceRef) -> dict[str, Any]:
    try:
        rows = connection.execute(
            "SELECT value FROM parquet_kv_metadata(?) WHERE key = 'geo'",
            [source.uri],
        ).fetchall()
    except duckdb.Error:
        raise SourceInvalid("source GeoParquet metadata is invalid") from None
    if len(rows) != 1:
        raise SourceInvalid("source GeoParquet metadata is missing")
    encoded = rows[0][0]
    if isinstance(encoded, (bytes, bytearray)):
        try:
            encoded = bytes(encoded).decode("utf-8")
        except UnicodeDecodeError as exc:
            raise SourceInvalid("source GeoParquet metadata is invalid") from exc
    try:
        value = json.loads(encoded)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise SourceInvalid("source GeoParquet metadata is invalid") from exc
    if not isinstance(value, dict):
        raise SourceInvalid("source GeoParquet metadata is invalid")
    return value


def _crs_is_crs84(value: object) -> bool:
    if value is None:
        return True
    if not isinstance(value, dict):
        return False
    identifier = value.get("id")
    if not isinstance(identifier, dict):
        return False
    authority = str(identifier.get("authority", "")).upper()
    code = str(identifier.get("code", "")).upper()
    return authority == "OGC" and code == "CRS84"


def _property_contract(arrow_type: str) -> _PropertyContract:
    value = arrow_type.lower()
    if value in ("string", "large_string"):
        return _PropertyContract("VARCHAR", "VARCHAR")
    if value == "bool":
        return _PropertyContract("BOOLEAN", "BOOLEAN")
    integer_types = {
        "int8": ("TINYINT", "INTEGER"),
        "int16": ("SMALLINT", "INTEGER"),
        "int32": ("INTEGER", "INTEGER"),
        "int64": ("BIGINT", "BIGINT"),
        "uint8": ("UTINYINT", "INTEGER"),
        "uint16": ("USMALLINT", "INTEGER"),
        "uint32": ("UINTEGER", "BIGINT"),
        # MVT integer values are signed. String preserves the complete uint64 domain.
        "uint64": ("UBIGINT", "VARCHAR"),
    }
    if value in integer_types:
        physical, mvt = integer_types[value]
        return _PropertyContract(physical, mvt)
    if value == "float":
        return _PropertyContract("FLOAT", "FLOAT")
    if value == "double":
        return _PropertyContract("DOUBLE", "DOUBLE")
    if value == "date32[day]":
        return _PropertyContract(
            "DATE",
            "VARCHAR",
            _ParquetLogicalContract("INT32", "DATE", "DateType()"),
        )
    time_contracts = {
        "time32[ms]": _ParquetLogicalContract(
            "INT32",
            "TIME_MILLIS",
            "TimeType(isAdjustedToUTC=1, "
            "unit=TimeUnit(MILLIS=MilliSeconds(), MICROS=<null>, NANOS=<null>))",
        ),
        "time64[us]": _ParquetLogicalContract(
            "INT64",
            "TIME_MICROS",
            "TimeType(isAdjustedToUTC=1, "
            "unit=TimeUnit(MILLIS=<null>, MICROS=MicroSeconds(), NANOS=<null>))",
        ),
        "time64[ns]": _ParquetLogicalContract(
            "INT64",
            None,
            "TimeType(isAdjustedToUTC=1, "
            "unit=TimeUnit(MILLIS=<null>, MICROS=<null>, NANOS=NanoSeconds()))",
        ),
    }
    if value in time_contracts:
        return _PropertyContract("TIME WITH TIME ZONE", "VARCHAR", time_contracts[value])
    timestamp = re.fullmatch(r"timestamp\[(ms|us|ns)(?:, tz=([^]]+))?\]", arrow_type)
    if timestamp is not None:
        unit = timestamp.group(1)
        timezone = timestamp.group(2)
        if timezone is not None and timezone != "UTC":
            raise SourceInvalid("source property schema is unsupported")
        has_timezone = timezone is not None
        physical = (
            "TIMESTAMP WITH TIME ZONE"
            if has_timezone
            else "TIMESTAMP_NS"
            if unit == "ns"
            else "TIMESTAMP"
        )
        parquet_type = {
            "ms": ("TIMESTAMP_MILLIS", "MilliSeconds()"),
            "us": ("TIMESTAMP_MICROS", "MicroSeconds()"),
            "ns": (None, "NanoSeconds()"),
        }
        converted, unit_name = parquet_type[unit]
        unit_fields = {
            "ms": f"MILLIS={unit_name}, MICROS=<null>, NANOS=<null>",
            "us": f"MILLIS=<null>, MICROS={unit_name}, NANOS=<null>",
            "ns": f"MILLIS=<null>, MICROS=<null>, NANOS={unit_name}",
        }
        logical = (
            f"TimestampType(isAdjustedToUTC={int(has_timezone)}, "
            f"unit=TimeUnit({unit_fields[unit]}))"
        )
        return _PropertyContract(
            physical,
            "VARCHAR",
            _ParquetLogicalContract("INT64", converted, logical),
        )
    raise SourceInvalid("source property schema is unsupported")


def _base_type(value: str) -> str:
    return value.split("(", 1)[0].strip().upper()


def _read_top_level_parquet_fields(connection: Any, source: SourceRef) -> dict[str, _ParquetField]:
    try:
        rows = connection.execute(
            "SELECT name, type, num_children, converted_type, logical_type FROM parquet_schema(?)",
            [source.uri],
        ).fetchall()
    except duckdb.Error:
        raise SourceInvalid("source Parquet logical schema is invalid") from None
    if not rows or len(rows[0]) != 5 or type(rows[0][2]) is not int:
        raise SourceInvalid("source Parquet logical schema is invalid")

    def child_count(index: int) -> int:
        value = rows[index][2]
        if value is None:
            return 0
        if type(value) is not int or value < 0:
            raise SourceInvalid("source Parquet logical schema is invalid")
        return value

    def after_subtree(index: int) -> int:
        if not 0 <= index < len(rows):
            raise SourceInvalid("source Parquet logical schema is invalid")
        next_index = index + 1
        for _ in range(child_count(index)):
            next_index = after_subtree(next_index)
        return next_index

    fields: dict[str, _ParquetField] = {}
    index = 1
    for _ in range(child_count(0)):
        if not 0 <= index < len(rows) or not isinstance(rows[index][0], str):
            raise SourceInvalid("source Parquet logical schema is invalid")
        name = rows[index][0]
        if name in fields:
            raise SourceInvalid("source Parquet logical schema is invalid")
        values = rows[index][1], rows[index][3], rows[index][4]
        if any(value is not None and not isinstance(value, str) for value in values):
            raise SourceInvalid("source Parquet logical schema is invalid")
        fields[name] = _ParquetField(*values)
        index = after_subtree(index)
    if index != len(rows):
        raise SourceInvalid("source Parquet logical schema is invalid")
    return fields


def _covering_paths(geometry_metadata: dict[str, Any]) -> tuple[str, dict[str, str]]:
    covering = geometry_metadata.get("covering")
    bbox = covering.get("bbox") if isinstance(covering, dict) else None
    if not isinstance(bbox, dict) or set(bbox) != {"xmin", "ymin", "xmax", "ymax"}:
        raise SourceInvalid("source covering metadata is invalid")
    column: str | None = None
    fields: dict[str, str] = {}
    for logical in ("xmin", "ymin", "xmax", "ymax"):
        path = bbox.get(logical)
        if (
            not isinstance(path, list)
            or len(path) != 2
            or any(not isinstance(item, str) or not item for item in path)
        ):
            raise SourceInvalid("source covering metadata is invalid")
        if column is None:
            column = path[0]
        elif path[0] != column:
            raise SourceInvalid("source covering metadata is invalid")
        fields[logical] = path[1]
    if column is None or len(set(fields.values())) != 4:
        raise SourceInvalid("source covering metadata is invalid")
    return column, fields


def _geometry_family(types: object) -> str | None:
    if not isinstance(types, list) or not types:
        return None
    if any(not isinstance(item, str) for item in types) or len(set(types)) != len(types):
        return None
    families = {_GEOPARQUET_GEOMETRY_FAMILY.get(item) for item in types}
    if None in families:
        return None
    return next(iter(families)) if len(families) == 1 else None


def _validate_dataset_bbox(value: object, expected: tuple[float, float, float, float]) -> None:
    if (
        not isinstance(value, list)
        or len(value) != 4
        or any(type(item) not in (int, float) or not math.isfinite(item) for item in value)
    ):
        raise SourceInvalid("source dataset bbox metadata is invalid")
    for index, (actual_value, expected_value) in enumerate(zip(value, expected, strict=True)):
        actual = float(actual_value)
        tolerance = max(abs(expected_value), 1.0) * 2**-22
        contains = actual <= expected_value if index < 2 else actual >= expected_value
        if not contains or abs(actual - expected_value) > tolerance:
            raise SourceInvalid("source dataset bbox disagrees with the manifest")


def _validate_source(connection: Any, source: SourceRef, manifest: LayerManifest) -> _SourceSchema:
    if not source.is_s3:
        path = Path(source.uri)
        try:
            valid_local_file = path.is_file() and path.stat().st_size == manifest.source_bytes
        except OSError:
            valid_local_file = False
        if not valid_local_file:
            raise SourceInvalid("source file is absent or has an invalid size")
    geo = _read_geo_metadata(connection, source)
    if geo.get("version") != "1.1.0":
        raise SourceInvalid("source GeoParquet metadata version is invalid")
    geometry_column = geo.get("primary_column")
    columns = geo.get("columns")
    if not isinstance(geometry_column, str) or not isinstance(columns, dict):
        raise SourceInvalid("source GeoParquet schema metadata is invalid")
    geometry_metadata = columns.get(geometry_column)
    if not isinstance(geometry_metadata, dict):
        raise SourceInvalid("source GeoParquet schema metadata is invalid")
    if geometry_metadata.get("encoding") != "WKB":
        raise SourceInvalid("source GeoParquet metadata encoding is invalid")
    if not _crs_is_crs84(geometry_metadata.get("crs")):
        raise SourceInvalid("source CRS is not OGC:CRS84")
    if _geometry_family(geometry_metadata.get("geometry_types")) != manifest.geometry_type:
        raise SourceInvalid("source geometry family disagrees with the manifest")
    _validate_dataset_bbox(geometry_metadata.get("bbox"), manifest.bbox)
    covering_column, covering_fields = _covering_paths(geometry_metadata)

    try:
        described = connection.execute(
            "DESCRIBE SELECT * FROM read_parquet(?)", [source.uri]
        ).fetchall()
        total = connection.execute("SELECT count(*) FROM read_parquet(?)", [source.uri]).fetchone()
    except duckdb.Error:
        raise SourceInvalid("source physical schema is invalid") from None
    physical_types = {str(row[0]): str(row[1]).upper() for row in described}
    parquet_fields = _read_top_level_parquet_fields(connection, source)
    expected = {
        geometry_column,
        covering_column,
        "__feature_id",
        *manifest.property_columns.values(),
    }
    if set(physical_types) != expected or set(parquet_fields) != expected:
        raise SourceInvalid("source physical schema disagrees with the manifest")
    if _base_type(physical_types[geometry_column]) not in ("BLOB", "GEOMETRY"):
        raise SourceInvalid("source geometry schema is invalid")
    if _base_type(physical_types["__feature_id"]) != "BIGINT":
        raise SourceInvalid("source feature ID schema is invalid")
    if not physical_types[covering_column].startswith("STRUCT"):
        raise SourceInvalid("source covering schema is invalid")
    if total is None or type(total[0]) is not int or total[0] != manifest.feature_count:
        raise SourceInvalid("source row count disagrees with the manifest")

    properties: list[tuple[str, str, str]] = []
    for display_name, physical_name in manifest.property_columns.items():
        contract = _property_contract(manifest.property_types[display_name])
        actual_type = _base_type(physical_types[physical_name])
        if actual_type != contract.duckdb_type:
            raise SourceInvalid("source property schema disagrees with the manifest")
        if contract.parquet is not None:
            field = parquet_fields[physical_name]
            if field != _ParquetField(
                contract.parquet.physical_type,
                contract.parquet.converted_type,
                contract.parquet.logical_type,
            ):
                raise SourceInvalid("source property schema disagrees with the manifest")
        properties.append((display_name, physical_name, contract.mvt_type))
    return _SourceSchema(
        geometry_column=geometry_column,
        geometry_is_blob=_base_type(physical_types[geometry_column]) == "BLOB",
        covering_column=covering_column,
        covering_fields=covering_fields,
        properties=tuple(properties),
        family=manifest.geometry_type,
    )


def _tile_bounds_4326(coord: TileCoord) -> tuple[float, float, float, float]:
    count = 2**coord.z

    def longitude(value: float) -> float:
        return float(value / count * 360.0 - 180.0)

    def latitude(value: float) -> float:
        return math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * value / count))))

    return (
        longitude(coord.x),
        latitude(coord.y + 1),
        longitude(coord.x + 1),
        latitude(coord.y),
    )


def _simplify_tolerance(zoom: int) -> float:
    return float(SIMPLIFY_PIXELS * WEBMERCATOR_RESOLUTION_Z0 / (2**zoom))


def _bbox_predicate(schema: _SourceSchema, bounds: tuple[float, ...]) -> str:
    west, south, east, north = bounds

    def edge(logical: str) -> str:
        field = schema.covering_fields[logical]
        return (
            f"CAST(struct_extract({_quote_identifier(schema.covering_column)}, "
            f"{_quote_literal(field)}) AS DOUBLE)"
        )

    return (
        f"{edge('xmax')} >= {west!r} AND {edge('xmin')} <= {east!r} AND "
        f"{edge('ymax')} >= {south!r} AND {edge('ymin')} <= {north!r}"
    )


def _repair(expression: str, family: str) -> str:
    return f"ST_CollectionExtract(ST_MakeValid({expression}), {_FAMILY_CODE[family]})"


def _point_grid_bins(max_features: int) -> tuple[int, int]:
    buffered_span = MVT_EXTENT + 2 * MVT_BUFFER + 1
    minimum_cell_width = math.ceil(POINT_GRID_PIXELS * MVT_EXTENT / 256.0)
    maximum_axis_bins = max(1, buffered_span // minimum_cell_width)
    x_bins = min(maximum_axis_bins, max(1, math.isqrt(max_features)))
    y_bins = min(maximum_axis_bins, max(1, max_features // x_bins))
    return x_bins, y_bins


def _point_bin_expression(geometry: str, axis: Literal["X", "Y"], bins: int) -> str:
    # ST_AsMVTGeom can emit coordinates from -buffer through extent+buffer.
    # Mapping that inclusive integer span into [0, bins - 1], then clamping,
    # makes the number of possible (x, y) partitions exactly x_bins*y_bins.
    span = MVT_EXTENT + 2 * MVT_BUFFER + 1
    coordinate = f"ST_{axis}(ST_Centroid({geometry}))"
    scaled = f"floor((({coordinate} + {MVT_BUFFER}) * {bins}) / {span})"
    return f"LEAST({bins - 1}, GREATEST(0, CAST({scaled} AS BIGINT)))"


def _build_ctes(
    schema: _SourceSchema,
    coord: TileCoord,
    limits: RenderLimits,
) -> str:
    geometry_alias, feature_id_alias = _internal_aliases(schema)
    quoted_geometry_alias = _quote_identifier(geometry_alias)
    quoted_feature_id_alias = _quote_identifier(feature_id_alias)
    source_columns = [schema.geometry_column, "__feature_id"] + [
        physical for _, physical, _ in schema.properties
    ]
    source_projection = ", ".join(_quote_identifier(name) for name in source_columns)
    property_projection = "".join(
        f", CAST({_quote_identifier(physical)} AS {target}) AS {_quote_identifier(display)}"
        for display, physical, target in schema.properties
    )
    property_carry = "".join(
        f", {_quote_identifier(display)}" for display, _, _ in schema.properties
    )
    raw_geometry = _quote_identifier(schema.geometry_column)
    if schema.geometry_is_blob:
        raw_geometry = f"ST_GeomFromWKB({raw_geometry})"
    geometry = _repair(raw_geometry, schema.family)
    dimension = _FAMILY_DIMENSION[schema.family]
    tolerance = _simplify_tolerance(coord.z)
    if schema.family == "polygon":
        prepared = _repair(
            f"ST_SimplifyPreserveTopology({quoted_geometry_alias}, {tolerance!r})",
            schema.family,
        )
    elif schema.family == "line":
        prepared = f"ST_Simplify({quoted_geometry_alias}, {tolerance!r})"
    else:
        prepared = quoted_geometry_alias
    envelope = f"ST_Extent(ST_TileEnvelope({coord.z}, {coord.x}, {coord.y}))"
    ctes = (
        "candidates AS MATERIALIZED (\n"
        f"  SELECT {source_projection} FROM read_parquet(?)\n"
        f"  WHERE {_bbox_predicate(schema, _tile_bounds_4326(coord))}\n"
        "),\n"
        "decoded AS MATERIALIZED (\n"
        f"  SELECT {geometry} AS {quoted_geometry_alias}, "
        f"CAST({_quote_identifier('__feature_id')} AS BIGINT) AS {quoted_feature_id_alias}"
        f"{property_projection}\n"
        "  FROM candidates\n"
        "),\n"
        "projected AS (\n"
        f"  SELECT ST_Transform({quoted_geometry_alias}, 'OGC:CRS84', 'EPSG:3857', "
        f"always_xy := true) AS {quoted_geometry_alias}, {quoted_feature_id_alias}"
        f"{property_carry}\n"
        f"  FROM decoded WHERE {quoted_geometry_alias} IS NOT NULL "
        f"AND NOT ST_IsEmpty({quoted_geometry_alias}) "
        f"AND ST_Dimension({quoted_geometry_alias}) = {dimension}\n"
        "),\n"
        "prepared AS (\n"
        f"  SELECT {prepared} AS {quoted_geometry_alias}, {quoted_feature_id_alias}"
        f"{property_carry} FROM projected\n"
        "),\n"
        "tile_geometry AS (\n"
        f"  SELECT ST_AsMVTGeom({quoted_geometry_alias}, {envelope}, {MVT_EXTENT}, "
        f"{MVT_BUFFER}, true) AS {quoted_geometry_alias}, {quoted_feature_id_alias}"
        f"{property_carry}\n"
        f"  FROM prepared WHERE {quoted_geometry_alias} IS NOT NULL "
        f"AND NOT ST_IsEmpty({quoted_geometry_alias})\n"
        "),\n"
        "visible AS (\n"
        f"  SELECT {quoted_geometry_alias}, {quoted_feature_id_alias}{property_carry} "
        "FROM tile_geometry\n"
        f"  WHERE {quoted_geometry_alias} IS NOT NULL "
        f"AND NOT ST_IsEmpty({quoted_geometry_alias})\n"
        ")"
    )
    if schema.family == "point":
        x_bins, y_bins = _point_grid_bins(limits.max_features_encoded)
        x_bin = _point_bin_expression(quoted_geometry_alias, "X", x_bins)
        y_bin = _point_bin_expression(quoted_geometry_alias, "Y", y_bins)
        ctes += (
            ",\nfinal AS (\n"
            f"  SELECT {quoted_geometry_alias}, {quoted_feature_id_alias}{property_carry} "
            "FROM visible\n"
            "  QUALIFY row_number() OVER (\n"
            f"    PARTITION BY {x_bin}, {y_bin}\n"
            f"    ORDER BY {quoted_feature_id_alias}\n"
            "  ) = 1\n"
            ")"
        )
    else:
        ctes += ",\nfinal AS (SELECT * FROM visible)"
    return ctes


def _row_count_sql(schema: _SourceSchema, coord: TileCoord, limit: int) -> str:
    return (
        "SELECT count(*) FROM ("
        f"SELECT 1 FROM read_parquet(?) WHERE {_bbox_predicate(schema, _tile_bounds_4326(coord))} "
        f"LIMIT {limit + 1})"
    )


def _feature_count_sql(ctes: str, limit: int) -> str:
    return f"WITH {ctes} SELECT count(*) FROM (SELECT 1 FROM final LIMIT {limit + 1})"


def _render_sql(schema: _SourceSchema, ctes: str) -> str:
    geometry_alias, feature_id_alias = _internal_aliases(schema)
    struct_fields = [
        f"{_quote_literal(geometry_alias)}: {_quote_identifier(geometry_alias)}",
        f"{_quote_literal(feature_id_alias)}: {_quote_identifier(feature_id_alias)}",
    ] + [
        f"{_quote_literal(display)}: {_quote_identifier(display)}"
        for display, _, _ in schema.properties
    ]
    row = "{" + ", ".join(struct_fields) + "}"
    return (
        f"WITH {ctes} SELECT ST_AsMVT({row}, 'default', {MVT_EXTENT}, "
        f"{_quote_literal(geometry_alias)}, {_quote_literal(feature_id_alias)}) FROM final"
    )


def _one_integer(row: Any) -> int:
    if row is None or type(row[0]) is not int:
        raise SourceInvalid("source query returned an invalid count")
    return row[0]


def _check_deadline(timed_out: threading.Event) -> None:
    if timed_out.is_set():
        raise RenderTimedOut("tile rendering exceeded its deadline")


def _render_with_connection(
    connection: Any,
    source: SourceRef,
    manifest: LayerManifest,
    coord: TileCoord,
    limits: RenderLimits,
    timed_out: threading.Event,
) -> bytes:
    _check_deadline(timed_out)
    schema = _validate_source(connection, source, manifest)
    _check_deadline(timed_out)
    examined = _one_integer(
        connection.execute(
            _row_count_sql(schema, coord, limits.max_rows_examined), [source.uri]
        ).fetchone()
    )
    if examined > limits.max_rows_examined:
        raise TileTooLarge("tile exceeds the rows examined limit")
    ctes = _build_ctes(schema, coord, limits)
    _check_deadline(timed_out)
    encoded_features = _one_integer(
        connection.execute(
            _feature_count_sql(ctes, limits.max_features_encoded), [source.uri]
        ).fetchone()
    )
    if encoded_features > limits.max_features_encoded:
        raise TileTooLarge("tile exceeds the encoded features limit")
    if encoded_features == 0:
        return b""
    _check_deadline(timed_out)
    row = connection.execute(_render_sql(schema, ctes), [source.uri]).fetchone()
    _check_deadline(timed_out)
    value = row[0] if row else None
    body = bytes(value) if value else b""
    if len(body) > limits.max_mvt_bytes:
        raise TileTooLarge("tile exceeds the encoded bytes limit")
    return body


def render_tile(
    source: SourceRef,
    manifest: LayerManifest,
    coord: TileCoord,
    limits: RenderLimits,
) -> bytes:
    """Render one valid coordinate without retaining source or tile data."""
    if not isinstance(source, SourceRef):
        raise TypeError("source must be a SourceRef")
    if not isinstance(manifest, LayerManifest):
        raise TypeError("manifest must be a LayerManifest")
    if not isinstance(coord, TileCoord):
        raise TypeError("coord must be a TileCoord")
    if not isinstance(limits, RenderLimits):
        raise TypeError("limits must be RenderLimits")
    coord.validate(manifest.min_zoom, manifest.max_zoom)
    parent = limits.spill_directory
    if parent is not None:
        parent.mkdir(parents=True, exist_ok=True)
    spill = Path(
        tempfile.mkdtemp(prefix="sgs-mvt-spill-", dir=str(parent) if parent is not None else None)
    )
    connection: Any | None = None
    timer: threading.Timer | None = None
    timed_out = threading.Event()
    try:
        # In-memory connection construction is a bounded local-only seam: no source,
        # network, credential, or extension action occurs there, and there is not yet
        # a connection that a watchdog could interrupt. Everything after it is timed.
        connection = _new_connection()

        def interrupt() -> None:
            timed_out.set()
            if connection is not None:
                connection.interrupt()

        timer = threading.Timer(float(limits.timeout_seconds), interrupt)
        timer.daemon = True
        timer.start()
        _configure_connection(connection, source, limits, spill, timed_out)
        body = _render_with_connection(connection, source, manifest, coord, limits, timed_out)
        _check_deadline(timed_out)
        return body
    except (TileTooLarge, SourceInvalid, RenderTimedOut):
        raise
    except duckdb.Error:
        if timed_out.is_set():
            raise RenderTimedOut("tile rendering exceeded its deadline") from None
        raise SourceInvalid("source could not be rendered") from None
    finally:
        try:
            if timer is not None:
                timer.cancel()
                timer.join()
        finally:
            try:
                if connection is not None:
                    with contextlib.suppress(Exception):
                        connection.close()
            finally:
                shutil.rmtree(spill)
