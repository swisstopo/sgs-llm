"""Collision-safe durable source writer conformance."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Sequence

import numpy as np
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
import pytest
from pyproj import CRS
from shapely import from_wkb
from shapely.geometry import (
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
)

from . import artifacts


FUTURE = datetime(2026, 8, 11, tzinfo=UTC)


def feature(
    feature_id: int | str | None,
    properties: dict[str, Any],
    *,
    geometry: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "type": "Feature",
        "id": feature_id,
        "geometry": geometry or {"type": "Point", "coordinates": [7.44, 46.95]},
        "properties": properties,
    }


def two_far_apart_polygons() -> list[dict[str, Any]]:
    east = {
        "type": "Polygon",
        "coordinates": [[[8.0, 46.0], [8.2, 46.0], [8.2, 46.2], [8.0, 46.0]]],
    }
    west = {
        "type": "Polygon",
        "coordinates": [[[6.0, 46.0], [6.2, 46.0], [6.2, 46.2], [6.0, 46.0]]],
    }
    return [
        feature(2, {"name": "east"}, geometry=east),
        feature(1, {"name": "west"}, geometry=west),
    ]


def _promote_geometry(value: bytes) -> bytes:
    geometry = from_wkb(value)
    if geometry.geom_type == "Point":
        return MultiPoint([geometry]).wkb
    if geometry.geom_type == "LineString":
        return MultiLineString([geometry]).wkb
    if geometry.geom_type == "Polygon":
        return MultiPolygon([geometry]).wkb
    return geometry.wkb


def install_fake_ogr(
    monkeypatch: pytest.MonkeyPatch,
    *,
    remove_covering: bool = False,
    omit_crs: bool = False,
    float32_covering: bool = False,
    inspect_source: Callable[[pa.Table], None] | None = None,
    mutate_output: Callable[[pa.Table, dict[str, Any]], pa.Table] | None = None,
) -> list[tuple[list[str], dict[str, str]]]:
    """Replace only the external OGR process; retain real intermediate/output I/O."""
    calls: list[tuple[list[str], dict[str, str]]] = []

    def run(command: list[str], env: dict[str, str]) -> None:
        calls.append((command, env))
        output, source = Path(command[3]), Path(command[4])
        table = pq.read_table(source)
        if inspect_source is not None:
            inspect_source(table)

        geometries = [
            _promote_geometry(value) for value in table["geometry"].to_pylist()
        ]
        bounds = [from_wkb(value).bounds for value in geometries]
        order = sorted(
            range(len(bounds)), key=lambda index: (bounds[index][0], bounds[index][1])
        )
        table = table.set_column(
            table.schema.get_field_index("geometry"),
            "geometry",
            pa.array(geometries, type=pa.binary()),
        )
        table = table.take(pa.array(order, type=pa.int64()))
        bounds = [bounds[index] for index in order]

        metadata = dict(table.schema.metadata or {})
        geo = json.loads(metadata[b"geo"])
        geometry_types = sorted({from_wkb(value).geom_type for value in geometries})
        geometry_metadata = geo["columns"]["geometry"]
        if omit_crs:
            geometry_metadata.pop("crs", None)
        geometry_metadata["geometry_types"] = geometry_types
        geometry_metadata["bbox"] = [
            min(item[0] for item in bounds),
            min(item[1] for item in bounds),
            max(item[2] for item in bounds),
            max(item[3] for item in bounds),
        ]
        if not remove_covering:
            covering_type = pa.float32() if float32_covering else pa.float64()
            minima_offset = -1e-6 if float32_covering else 0.0
            maxima_offset = 1e-6 if float32_covering else 0.0
            bbox = pa.StructArray.from_arrays(
                [
                    pa.array(
                        [item[0] + minima_offset for item in bounds],
                        type=covering_type,
                    ),
                    pa.array(
                        [item[1] + minima_offset for item in bounds],
                        type=covering_type,
                    ),
                    pa.array(
                        [item[2] + maxima_offset for item in bounds],
                        type=covering_type,
                    ),
                    pa.array(
                        [item[3] + maxima_offset for item in bounds],
                        type=covering_type,
                    ),
                ],
                names=["xmin", "ymin", "xmax", "ymax"],
            )
            table = table.append_column("bbox", bbox)
            geometry_metadata["covering"] = {
                "bbox": {
                    "xmin": ["bbox", "xmin"],
                    "ymin": ["bbox", "ymin"],
                    "xmax": ["bbox", "xmax"],
                    "ymax": ["bbox", "ymax"],
                }
            }
        if mutate_output is not None:
            table = mutate_output(table, geo)
        metadata[b"geo"] = json.dumps(geo, separators=(",", ":")).encode()
        pq.write_table(
            table.replace_schema_metadata(metadata),
            output,
            compression="snappy",
            row_group_size=500_000,
        )

    monkeypatch.setattr(artifacts, "_run_ogr2ogr", run, raising=False)
    return calls


def _replace_covering(
    table: pa.Table,
    bounds: list[tuple[float | None, float | None, float | None, float | None]],
    *,
    field_type: pa.DataType = pa.float64(),
) -> pa.Table:
    covering = pa.StructArray.from_arrays(
        [
            pa.array([item[index] for item in bounds], type=field_type)
            for index in range(4)
        ],
        names=["xmin", "ymin", "xmax", "ymax"],
    )
    return table.set_column(table.schema.get_field_index("bbox"), "bbox", covering)


def _replace_first_geometry_with_distant_point(
    table: pa.Table, _geo: dict[str, Any]
) -> pa.Table:
    geometries = table["geometry"].to_pylist()
    distant = MultiPoint([Point(80.0, 10.0)])
    geometries[0] = distant.wkb
    table = table.set_column(
        table.schema.get_field_index("geometry"),
        "geometry",
        pa.array(geometries, type=pa.binary()),
    )
    bounds = [from_wkb(value).bounds for value in geometries]
    return _replace_covering(table, bounds)


def _swap_internal_ids(table: pa.Table, _geo: dict[str, Any]) -> pa.Table:
    ids = list(reversed(table["__feature_id"].to_pylist()))
    return table.set_column(
        table.schema.get_field_index("__feature_id"),
        "__feature_id",
        pa.array(ids, type=pa.int64()),
    )


def test_accepts_geoparquet_default_crs_when_ogr_omits_crs_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_ogr(monkeypatch, omit_crs=True)

    artifact = artifacts.write_source(
        [feature(1, {"name": "Bern"})],
        tmp_path / "source.parquet",
        expires_at=FUTURE,
        complete=True,
    )

    geo = json.loads((pq.read_metadata(artifact.path).metadata or {})[b"geo"])
    assert "crs" not in geo["columns"]["geometry"]
    assert artifact.manifest.crs == "OGC:CRS84"


def test_accepts_gdal_float32_covering_that_conservatively_contains_wkb(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_ogr(monkeypatch, float32_covering=True)

    artifact = artifacts.write_source(
        two_far_apart_polygons(),
        tmp_path / "source.parquet",
        expires_at=FUTURE,
        complete=True,
    )
    table = pq.read_table(artifact.path)
    assert table.schema.field("bbox").type == pa.struct(
        [
            pa.field("xmin", pa.float32()),
            pa.field("ymin", pa.float32()),
            pa.field("xmax", pa.float32()),
            pa.field("ymax", pa.float32()),
        ]
    )


@pytest.mark.parametrize(
    "mutation",
    [_replace_first_geometry_with_distant_point, _swap_internal_ids],
    ids=["distant-same-family-geometry", "swapped-feature-ids"],
)
def test_validation_associates_converted_geometry_with_internal_feature_id(
    mutation: Callable[[pa.Table, dict[str, Any]], pa.Table],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_ogr(monkeypatch, mutate_output=mutation)
    features = [
        feature(1, {}, geometry={"type": "Point", "coordinates": [7.0, 46.0]}),
        feature(2, {}, geometry={"type": "Point", "coordinates": [8.0, 47.0]}),
    ]

    with pytest.raises(artifacts.SourceValidationError, match="feature ID"):
        artifacts.write_source(
            features,
            tmp_path / "source.parquet",
            expires_at=FUTURE,
            complete=True,
        )


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (
            lambda table, geo: geo.__setitem__("version", "1.0.0") or table,
            "version",
        ),
        (
            lambda table, geo: (
                geo["columns"]["geometry"].__setitem__("bbox", [7.1, 46.0, 8.0, 47.0])
                or table
            ),
            "dataset bbox",
        ),
        (
            lambda table, geo: (
                geo["columns"]["geometry"].__setitem__("bbox", [6.0, 45.0, 9.0, 48.0])
                or table
            ),
            "dataset bbox",
        ),
    ],
    ids=["wrong-version", "inward-dataset-bbox", "excessive-dataset-bbox"],
)
def test_validation_rejects_wrong_geoparquet_version_or_dataset_bbox(
    mutation: Callable[[pa.Table, dict[str, Any]], pa.Table],
    match: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_ogr(monkeypatch, mutate_output=mutation)
    features = [
        feature(1, {}, geometry={"type": "Point", "coordinates": [7.0, 46.0]}),
        feature(2, {}, geometry={"type": "Point", "coordinates": [8.0, 47.0]}),
    ]

    with pytest.raises(artifacts.SourceValidationError, match=match):
        artifacts.write_source(
            features,
            tmp_path / "source.parquet",
            expires_at=FUTURE,
            complete=True,
        )


@pytest.mark.parametrize("malformed", [[], "not-an-object"])
def test_validation_normalizes_malformed_geometry_metadata(
    malformed: object,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def mutate(table: pa.Table, geo: dict[str, Any]) -> pa.Table:
        geo["columns"]["geometry"] = malformed
        return table

    install_fake_ogr(monkeypatch, mutate_output=mutate)

    with pytest.raises(
        artifacts.SourceValidationError, match="GeoParquet geo metadata"
    ):
        artifacts.write_source(
            [feature(1, {})],
            tmp_path / "source.parquet",
            expires_at=FUTURE,
            complete=True,
        )


def _set_non_crs84(table: pa.Table, geo: dict[str, Any]) -> pa.Table:
    geo["columns"]["geometry"]["crs"] = CRS.from_epsg(3857).to_json_dict()
    return table


def _set_inward_covering(table: pa.Table, _geo: dict[str, Any]) -> pa.Table:
    bounds = [from_wkb(value).bounds for value in table["geometry"].to_pylist()]
    inward = [(west + 0.001, south, east, north) for west, south, east, north in bounds]
    return _replace_covering(table, inward, field_type=pa.float32())


def _set_excessive_covering(table: pa.Table, _geo: dict[str, Any]) -> pa.Table:
    bounds = [from_wkb(value).bounds for value in table["geometry"].to_pylist()]
    excessive = [
        (west - 1.0, south - 1.0, east + 1.0, north + 1.0)
        for west, south, east, north in bounds
    ]
    return _replace_covering(table, excessive, field_type=pa.float32())


def _set_null_covering(table: pa.Table, _geo: dict[str, Any]) -> pa.Table:
    bounds = [from_wkb(value).bounds for value in table["geometry"].to_pylist()]
    nullable = [(None, south, east, north) for _, south, east, north in bounds]
    return _replace_covering(table, nullable)


def _remove_covering_path(table: pa.Table, geo: dict[str, Any]) -> pa.Table:
    del geo["columns"]["geometry"]["covering"]["bbox"]["ymin"]
    return table


def _set_wrong_covering_path(table: pa.Table, geo: dict[str, Any]) -> pa.Table:
    geo["columns"]["geometry"]["covering"]["bbox"]["xmin"] = [
        "missing_bbox",
        "xmin",
    ]
    return table


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (_set_non_crs84, "CRS"),
        (_set_inward_covering, "covering bbox"),
        (_set_excessive_covering, "covering bbox"),
        (_set_null_covering, "covering bbox"),
        (_remove_covering_path, "covering"),
        (_set_wrong_covering_path, "covering"),
    ],
    ids=[
        "non-crs84",
        "inward-float",
        "excessive-outward-float",
        "null-value",
        "missing-path",
        "wrong-path",
    ],
)
def test_validation_rejects_invalid_crs_and_covering_mutations(
    mutation: Callable[[pa.Table, dict[str, Any]], pa.Table],
    match: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    install_fake_ogr(monkeypatch, mutate_output=mutation)

    with pytest.raises(artifacts.SourceValidationError, match=match):
        artifacts.write_source(
            [feature(1, {})],
            tmp_path / "source.parquet",
            expires_at=FUTURE,
            complete=True,
        )


def test_source_columns_are_injective_and_feature_ids_are_int64(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_ogr(monkeypatch)
    features = [
        feature(7, {"feature_id": "public", "property_feature_id": "also-public"})
    ]

    artifact = artifacts.write_source(
        features,
        tmp_path / "source.parquet",
        expires_at=FUTURE,
        complete=True,
    )

    table = pq.read_table(artifact.path)
    assert table.schema.field("__feature_id").type == pa.int64()
    assert table["__feature_id"].to_pylist() == [0]
    assert len(set(artifact.manifest.property_columns.values())) == 2
    assert (
        table.column(artifact.manifest.property_columns["feature_id"])[0].as_py()
        == "public"
    )
    assert (
        table.column(artifact.manifest.property_columns["property_feature_id"])[
            0
        ].as_py()
        == "also-public"
    )


def test_property_names_escape_bytes_and_reserve_physical_columns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_ogr(monkeypatch)
    properties = {
        "a-b": "hyphen",
        "a_2db": "literal escape",
        "é": "utf8",
        "geometry": "public geometry",
        "bbox": "public bbox",
        "__sgs_private": "public reserved-looking name",
    }

    artifact = artifacts.write_source(
        [feature(1, properties)],
        tmp_path / "source.parquet",
        expires_at=FUTURE,
        complete=True,
    )

    mapping = artifact.manifest.property_columns
    assert mapping["a-b"] == "a_2db"
    assert mapping["a_2db"] == "a_5f2db"
    assert mapping["é"] == "_c3_a9"
    assert len(set(mapping.values())) == len(mapping)
    assert not ({"geometry", "bbox", "__feature_id"} & set(mapping.values()))
    assert all(not name.startswith("__sgs_") for name in mapping.values())
    row = pq.read_table(artifact.path).to_pylist()[0]
    assert {
        original: row[physical] for original, physical in mapping.items()
    } == properties


def test_deduplicates_public_ids_before_assigning_stable_internal_ids(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_ogr(monkeypatch)
    features = [
        feature("same", {"name": "first"}),
        feature("same", {"name": "duplicate"}),
        feature(None, {"name": "anonymous one"}),
        feature(None, {"name": "anonymous two"}),
    ]

    artifact = artifacts.write_source(
        features, tmp_path / "source.parquet", expires_at=FUTURE, complete=False
    )

    table = pq.read_table(artifact.path).to_pydict()
    name_column = artifact.manifest.property_columns["name"]
    rows = dict(zip(table["__feature_id"], table[name_column], strict=True))
    assert rows == {0: "first", 1: "anonymous one", 2: "anonymous two"}
    assert artifact.manifest.feature_count == 3
    assert artifact.manifest.complete is False


def test_preserves_compatible_scalars_and_serializes_conflicts_deterministically(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_ogr(monkeypatch)
    features = [
        feature(1, {"flag": True, "count": 2, "measure": 2, "mixed": 3}),
        feature(2, {"measure": 2.5, "mixed": {"b": 2, "a": 1}}),
    ]

    artifact = artifacts.write_source(
        features, tmp_path / "source.parquet", expires_at=FUTURE, complete=True
    )

    table = pq.read_table(artifact.path)
    columns = artifact.manifest.property_columns
    assert table[columns["flag"]].type == pa.bool_()
    assert table[columns["count"]].type == pa.int64()
    assert table[columns["measure"]].type == pa.float64()
    assert table[columns["mixed"]].to_pylist() == ["3", '{"a":1,"b":2}']
    assert artifact.manifest.property_types == {
        "count": "int64",
        "flag": "bool",
        "measure": "double",
        "mixed": "string",
    }


def test_source_has_geoparquet_covering_wkb_and_spatial_layout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_ogr(monkeypatch)

    artifact = artifacts.write_source(
        two_far_apart_polygons(),
        tmp_path / "source.parquet",
        expires_at=FUTURE,
        complete=True,
    )

    metadata = pq.read_metadata(artifact.path).metadata or {}
    geo = json.loads(metadata[b"geo"])
    covering = geo["columns"]["geometry"]["covering"]
    assert covering["bbox"]["xmin"] == ["bbox", "xmin"]
    table = pq.read_table(artifact.path)
    assert table["bbox"].type == pa.struct(
        [
            pa.field("xmin", pa.float64()),
            pa.field("ymin", pa.float64()),
            pa.field("xmax", pa.float64()),
            pa.field("ymax", pa.float64()),
        ]
    )
    assert [from_wkb(value).geom_type for value in table["geometry"].to_pylist()] == [
        "MultiPolygon",
        "MultiPolygon",
    ]
    name_column = artifact.manifest.property_columns["name"]
    assert table[name_column].to_pylist() == ["west", "east"]
    assert (
        artifact.manifest.source_sha256
        == sha256(artifact.path.read_bytes()).hexdigest()
    )
    assert artifact.checksum == artifact.manifest.source_sha256
    assert (
        artifact.byte_count
        == artifact.path.stat().st_size
        == artifact.manifest.source_bytes
    )


def test_uses_exact_ogr_argument_array_and_standard_parquet_intermediate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict[str, Any] = {}

    def inspect_source(table: pa.Table) -> None:
        seen["schema"] = table.schema
        seen["geometry"] = [
            from_wkb(value).geom_type for value in table["geometry"].to_pylist()
        ]

    calls = install_fake_ogr(monkeypatch, inspect_source=inspect_source)
    output = tmp_path / "source.parquet"

    artifacts.write_source(
        [feature(1, {"name": "Bern"})], output, expires_at=FUTURE, complete=True
    )

    assert len(calls) == 1
    command, env = calls[0]
    assert command[:3] == ["ogr2ogr", "-f", "Parquet"]
    assert command[3].endswith("/converted.parquet")
    assert command[4].endswith("/standard.parquet")
    assert command[5:] == [
        "-lco",
        "COMPRESSION=SNAPPY",
        "-lco",
        "ROW_GROUP_SIZE=10000",
        "-lco",
        "GEOMETRY_ENCODING=WKB",
        "-lco",
        "SORT_BY_BBOX=YES",
        "-lco",
        "WRITE_COVERING_BBOX=YES",
        "-nlt",
        "PROMOTE_TO_MULTI",
    ]
    assert env["OGR2OGR_USE_ARROW_API"] == "YES"
    schema = seen["schema"]
    assert schema.field("geometry").type == pa.binary()
    assert b"geo" in (schema.metadata or {})
    assert seen["geometry"] == ["Point"]


def test_source_checksum_is_streamed_instead_of_reading_the_whole_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_ogr(monkeypatch)
    original = Path.read_bytes

    def guarded_read(path: Path) -> bytes:
        if path.name == "converted.parquet":
            raise AssertionError("converted source must not be loaded fully for hashing")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", guarded_read)

    artifact = artifacts.write_source(
        [feature(1, {"name": "Bern"})],
        tmp_path / "source.parquet",
        expires_at=FUTURE,
        complete=True,
    )

    assert artifact.byte_count > 0


def test_rejects_empty_mixed_family_and_invalid_geometry_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_ogr(monkeypatch)
    line = {"type": "LineString", "coordinates": [[7.0, 46.0], [7.1, 46.1]]}

    with pytest.raises(ValueError, match="at least one feature"):
        artifacts.write_source(
            [], tmp_path / "empty.parquet", expires_at=FUTURE, complete=True
        )
    with pytest.raises(ValueError, match="one geometry family"):
        artifacts.write_source(
            [feature(1, {}, geometry=line), feature(2, {})],
            tmp_path / "mixed.parquet",
            expires_at=FUTURE,
            complete=True,
        )
    with pytest.raises(ValueError, match="invalid GeoJSON geometry"):
        artifacts.write_source(
            [feature(1, {}, geometry={"type": "Point", "coordinates": ["bad", 46.0]})],
            tmp_path / "invalid.parquet",
            expires_at=FUTURE,
            complete=True,
        )


def test_failed_conversion_or_validation_never_promotes_a_partial_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = tmp_path / "source.parquet"

    def fail(_command: list[str], _env: dict[str, str]) -> None:
        raise RuntimeError("ogr failed precisely")

    monkeypatch.setattr(artifacts, "_run_ogr2ogr", fail, raising=False)
    with pytest.raises(RuntimeError, match="ogr failed precisely"):
        artifacts.write_source(
            [feature(1, {})], output, expires_at=FUTURE, complete=True
        )
    assert not output.exists()

    install_fake_ogr(monkeypatch, remove_covering=True)
    with pytest.raises(artifacts.SourceValidationError, match="covering"):
        artifacts.write_source(
            [feature(1, {})], output, expires_at=FUTURE, complete=True
        )
    assert not output.exists()


def test_enforces_source_byte_ceiling_before_promotion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    install_fake_ogr(monkeypatch)
    monkeypatch.setattr(artifacts, "MAX_SOURCE_BYTES", 1, raising=False)
    output = tmp_path / "source.parquet"

    with pytest.raises(artifacts.ArtifactTooLarge, match="maximum is 1 byte"):
        artifacts.write_source(
            [feature(1, {})], output, expires_at=FUTURE, complete=True
        )

    assert not output.exists()


def test_point_zoom_uses_density_and_grid_collision_caps(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dispersed_lon = np.array([-170.0, 170.0])
    dispersed_lat = np.array([-70.0, 70.0])
    close_lon = np.array([0.0, 0.00001])
    close_lat = np.array([0.0, 0.0])

    assert (
        artifacts._point_max_zoom(
            dispersed_lon, dispersed_lat, attribute_count=2, extent_cap=16
        )
        == 1
    )
    assert (
        artifacts._point_max_zoom(
            close_lon, close_lat, attribute_count=2, extent_cap=16
        )
        > 1
    )

    tile_x = np.repeat(np.arange(128, 168), 50)
    tile_y = np.tile(np.arange(128, 178), 40)
    dense_lon = (tile_x + 0.5) / 256.0 * 360.0 - 180.0
    dense_lat = np.degrees(
        np.arctan(np.sinh(math.pi * (1.0 - 2.0 * (tile_y + 0.5) / 256.0)))
    )
    density_budgets: list[int] = []
    original_find = artifacts._find_point_max_zoom

    def record_budget(
        longitude: np.ndarray,
        latitude: np.ndarray,
        maximum_density: int,
        extent_cap: int,
        *,
        extra_zoom: int = 0,
    ) -> int:
        density_budgets.append(maximum_density)
        return original_find(
            longitude,
            latitude,
            maximum_density,
            extent_cap,
            extra_zoom=extra_zoom,
        )

    monkeypatch.setattr(artifacts, "_find_point_max_zoom", record_budget)
    low_attribute_zoom = artifacts._point_max_zoom(
        dense_lon, dense_lat, attribute_count=0, extent_cap=16
    )
    high_attribute_zoom = artifacts._point_max_zoom(
        dense_lon, dense_lat, attribute_count=100, extent_cap=16
    )

    assert density_budgets == [6000, 1, 801, 1]
    assert low_attribute_zoom == 1
    assert high_attribute_zoom > low_attribute_zoom


def test_line_zoom_uses_sampled_projected_average_edge_length() -> None:
    line = LineString([(index / 1000.0, 0.0) for index in range(1001)])

    assert (
        artifacts._line_polygon_max_zoom(
            [line], total_coordinate_count=1001, extent_cap=16
        )
        == 10
    )


def test_large_zoom_scan_bounds_feature_and_vertex_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class SyntheticGeometries(Sequence[int]):
        feature_count = 1_000_000
        coordinates_per_feature = 10

        def __init__(self) -> None:
            self.reads = 0

        def __len__(self) -> int:
            return self.feature_count

        def __getitem__(self, index: int) -> int:
            if not 0 <= index < self.feature_count:
                raise IndexError(index)
            self.reads += 1
            return index

    geometries = SyntheticGeometries()
    projected_selections: list[tuple[int, ...]] = []

    def projected_average(selected: Sequence[int]) -> float:
        projected_selections.append(tuple(selected))
        return 100.0

    monkeypatch.setattr(
        artifacts, "_projected_average_edge_length", projected_average, raising=False
    )

    first = artifacts._line_polygon_max_zoom(
        geometries,
        total_coordinate_count=(
            geometries.feature_count * geometries.coordinates_per_feature
        ),
        extent_cap=16,
    )
    first_read_count = geometries.reads
    second = artifacts._line_polygon_max_zoom(
        geometries,
        total_coordinate_count=(
            geometries.feature_count * geometries.coordinates_per_feature
        ),
        extent_cap=16,
    )

    assert first == second
    assert len(projected_selections) == 2
    assert len(projected_selections[0]) == 50_000
    assert projected_selections[0] == projected_selections[1]
    assert first_read_count == 50_000
    assert geometries.reads == 100_000
    assert len(projected_selections[0]) * geometries.coordinates_per_feature <= 500_000
