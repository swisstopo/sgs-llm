"""Real GeoParquet -> DuckDB spatial -> MVT renderer coverage."""

from __future__ import annotations

import inspect
import math
import re
import threading
import time
from dataclasses import replace
from datetime import UTC, date, datetime
from datetime import time as clock_time
from hashlib import sha256
from pathlib import Path
from typing import Any

import mapbox_vector_tile
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from shapely import affinity
from shapely.geometry import (
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
    shape,
)
from shapely.wkt import loads as load_wkt
from tile_server.model import (
    InvalidTile,
    RenderLimits,
    SourceInvalid,
    SourceRef,
    TileCoord,
    TileTooLarge,
)
from tile_server.mvt import render_tile

from tests.fixtures.tiles.geoparquet import write_geoparquet as _write_geoparquet


def _tile_for(longitude: float, latitude: float, zoom: int = 12) -> TileCoord:
    count = 2**zoom
    x = int((longitude + 180.0) / 360.0 * count)
    mercator = math.asinh(math.tan(math.radians(latitude)))
    y = int((1.0 - mercator / math.pi) / 2.0 * count)
    return TileCoord(zoom, x, y)


def _point_at_tile_units(coord: TileCoord, x: float, y: float) -> Point:
    count = 2**coord.z
    longitude = (coord.x + x / 4096.0) / count * 360.0 - 180.0
    world_y = (coord.y + y / 4096.0) / count
    latitude = math.degrees(math.atan(math.sinh(math.pi * (1.0 - 2.0 * world_y))))
    return Point(longitude, latitude)


SWISS_TILE = _tile_for(7.45, 46.95)


def _decode(body: bytes) -> dict[str, Any]:
    assert body
    decoded = mapbox_vector_tile.decode(body)
    assert decoded["default"]["extent"] == 4096
    return decoded


def _features(body: bytes) -> list[dict[str, Any]]:
    return _decode(body)["default"]["features"]


def test_renders_real_point_line_and_multi_geometries_with_ids_and_properties(
    tmp_path: Path,
) -> None:
    cases = [
        (Point(7.45, 46.95), "Point"),
        (MultiPoint([(7.45, 46.95), (7.451, 46.951)]), "MultiPoint"),
        (LineString([(7.44, 46.94), (7.46, 46.96)]), "LineString"),
        (
            MultiLineString([[(7.44, 46.94), (7.45, 46.95)], [(7.45, 46.95), (7.46, 46.96)]]),
            "MultiLineString",
        ),
        (
            MultiPolygon([Polygon([(7.44, 46.94), (7.45, 46.94), (7.45, 46.95), (7.44, 46.94)])]),
            "MultiPolygon",
        ),
    ]
    for index, (geometry, expected) in enumerate(cases):
        source = tmp_path / f"source-{index}.parquet"
        manifest, _ = _write_geoparquet(
            source,
            [geometry],
            ids=[7],
            properties={"road name": ("road_name", pa.array(["H21"]))},
        )
        features = _features(
            render_tile(SourceRef(str(source)), manifest, SWISS_TILE, RenderLimits())
        )
        assert len(features) == 1
        assert features[0]["id"] == 7
        assert features[0]["properties"] == {"road name": "H21"}
        if expected.startswith("Multi"):
            assert features[0]["geometry"]["type"] in {expected, expected[5:]}
        else:
            assert features[0]["geometry"]["type"] == expected


def test_polygon_hole_survives_real_render_and_topology_is_valid(tmp_path: Path) -> None:
    source = tmp_path / "hole.parquet"
    polygon = Polygon(
        [(7.2, 46.2), (8.1, 46.2), (8.1, 46.9), (7.2, 46.9)],
        [[(7.499, 46.599), (7.501, 46.599), (7.501, 46.601), (7.499, 46.601)]],
    )
    manifest, _ = _write_geoparquet(source, [polygon])
    overview_tile = _tile_for(7.45, 46.6, zoom=8)

    feature = _features(
        render_tile(SourceRef(str(source)), manifest, overview_tile, RenderLimits())
    )[0]
    decoded_geometry = shape(feature["geometry"])

    assert feature["geometry"]["type"] == "Polygon"
    assert decoded_geometry.is_valid
    assert len(decoded_geometry.interiors) == 1
    assert Polygon(decoded_geometry.interiors[0]).area > 0


def test_invalid_polygon_is_repaired_and_collection_non_family_members_are_discarded(
    tmp_path: Path,
) -> None:
    source = tmp_path / "repair.parquet"
    # GEOS repairs this into a polygon plus a stray line in a GeometryCollection.
    invalid = load_wkt("POLYGON((0 0,2 0,1 1,2 0,2 2,0 2,0 0))")
    invalid = affinity.translate(
        affinity.scale(invalid, xfact=0.01, yfact=0.01, origin=(0, 0)),
        7.44,
        46.94,
    )
    assert not invalid.is_valid
    manifest, _ = _write_geoparquet(source, [invalid], family="polygon")

    features = _features(render_tile(SourceRef(str(source)), manifest, SWISS_TILE, RenderLimits()))

    assert features
    assert {item["geometry"]["type"] for item in features} <= {
        "Polygon",
        "MultiPolygon",
    }


def test_valid_empty_tile_returns_empty_bytes(tmp_path: Path) -> None:
    source = tmp_path / "empty.parquet"
    manifest, _ = _write_geoparquet(source, [Point(7.45, 46.95)])
    far_away = _tile_for(-120.0, -40.0)

    assert render_tile(SourceRef(str(source)), manifest, far_away, RenderLimits()) == b""


def test_covering_filter_prunes_malformed_wkb_before_geometry_decode(tmp_path: Path) -> None:
    source = tmp_path / "prune.parquet"
    manifest, _ = _write_geoparquet(
        source,
        [Point(7.45, 46.95), b"not-wkb"],
        ids=[4, 5],
    )

    features = _features(render_tile(SourceRef(str(source)), manifest, SWISS_TILE, RenderLimits()))

    assert [item["id"] for item in features] == [4]


def test_sql_quotes_physical_names_and_preserves_original_display_names(
    tmp_path: Path,
) -> None:
    source = tmp_path / "quote's source.parquet"
    manifest, _ = _write_geoparquet(
        source,
        [LineString([(7.44, 46.94), (7.46, 46.96)])],
        properties={
            "display ' name": ('odd"column', pa.array(["safe"])),
            "count": ("select", pa.array([3], type=pa.int32())),
        },
    )

    properties = _features(
        render_tile(SourceRef(str(source)), manifest, SWISS_TILE, RenderLimits())
    )[0]["properties"]

    assert properties == {"display ' name": "safe", "count": 3}


def test_display_properties_can_use_every_internal_sql_name(tmp_path: Path) -> None:
    source = tmp_path / "display-collisions.parquet"
    manifest, _ = _write_geoparquet(
        source,
        [Point(7.45, 46.95)],
        ids=[17],
        properties={
            "geom": ("property_geom", pa.array(["display geometry"])),
            "__feature_id": ("property_id", pa.array(["display ID"])),
            "__sgs_mvt_geometry": ("property_internal_geom", pa.array(["also display"])),
            "__sgs_mvt_feature_id": ("property_internal_id", pa.array([23], type=pa.int32())),
            "__sgs_mvt_geometry_": (
                "property_internal_geom_suffix",
                pa.array(["suffix display"]),
            ),
            "__sgs_mvt_feature_id_": (
                "property_internal_id_suffix",
                pa.array([29], type=pa.int32()),
            ),
        },
    )

    feature = _features(render_tile(SourceRef(str(source)), manifest, SWISS_TILE, RenderLimits()))[
        0
    ]

    assert feature["id"] == 17
    assert feature["properties"] == {
        "geom": "display geometry",
        "__feature_id": "display ID",
        "__sgs_mvt_geometry": "also display",
        "__sgs_mvt_feature_id": 23,
        "__sgs_mvt_geometry_": "suffix display",
        "__sgs_mvt_feature_id_": 29,
    }


def test_real_arrow_scalar_types_are_validated_and_cast_for_mvt(tmp_path: Path) -> None:
    source = tmp_path / "scalar-types.parquet"
    properties = {
        "int8": ("p_int8", pa.array([-8], type=pa.int8())),
        "int16": ("p_int16", pa.array([-16], type=pa.int16())),
        "int32": ("p_int32", pa.array([-32], type=pa.int32())),
        "int64": ("p_int64", pa.array([9_000_000_000], type=pa.int64())),
        "uint8": ("p_uint8", pa.array([8], type=pa.uint8())),
        "uint16": ("p_uint16", pa.array([16], type=pa.uint16())),
        "uint32": ("p_uint32", pa.array([4_000_000_000], type=pa.uint32())),
        "uint64": ("p_uint64", pa.array([9_000_000_000], type=pa.uint64())),
        "float": ("p_float", pa.array([1.25], type=pa.float32())),
        "double": ("p_double", pa.array([2.5], type=pa.float64())),
        "bool": ("p_bool", pa.array([True], type=pa.bool_())),
        "string": ("p_string", pa.array(["stable"], type=pa.string())),
        "date32": ("p_date32", pa.array([date(2026, 8, 11)], type=pa.date32())),
        "date64": ("p_date64", pa.array([date(2026, 8, 11)], type=pa.date64())),
        "time32s": (
            "p_time32s",
            pa.array([clock_time(1, 2, 3)], type=pa.time32("s")),
        ),
        "time32ms": (
            "p_time32ms",
            pa.array([clock_time(1, 2, 3, 4_000)], type=pa.time32("ms")),
        ),
        "time64us": (
            "p_time64us",
            pa.array([clock_time(1, 2, 3, 4_000)], type=pa.time64("us")),
        ),
        "time64ns": (
            "p_time64ns",
            pa.array([clock_time(1, 2, 3, 4_000)], type=pa.time64("ns")),
        ),
        "timestamp_s": (
            "p_timestamp_s",
            pa.array([datetime(2026, 8, 11, 1, 2, 3)], type=pa.timestamp("s")),
        ),
        "timestamp_ms": (
            "p_timestamp_ms",
            pa.array([datetime(2026, 8, 11, 1, 2, 3, 4_000)], type=pa.timestamp("ms")),
        ),
        "timestamp_us": (
            "p_timestamp_us",
            pa.array([datetime(2026, 8, 11, 1, 2, 3, 4_000)], type=pa.timestamp("us")),
        ),
        "timestamp_ns": (
            "p_timestamp_ns",
            pa.array([datetime(2026, 8, 11, 1, 2, 3, 4_000)], type=pa.timestamp("ns")),
        ),
        "timestamp_tz": (
            "p_timestamp_tz",
            pa.array(
                [datetime(2026, 8, 11, 1, 2, 3, tzinfo=UTC)],
                type=pa.timestamp("us", tz="UTC"),
            ),
        ),
    }
    manifest, _ = _write_geoparquet(
        source,
        [Point(7.45, 46.95)],
        properties=properties,
    )

    decoded = _features(render_tile(SourceRef(str(source)), manifest, SWISS_TILE, RenderLimits()))[
        0
    ]["properties"]

    assert decoded == {
        "int8": -8,
        "int16": -16,
        "int32": -32,
        "int64": 9_000_000_000,
        "uint8": 8,
        "uint16": 16,
        "uint32": 4_000_000_000,
        "uint64": "9000000000",
        "float": 1.25,
        "double": 2.5,
        "bool": True,
        "string": "stable",
        "date32": "2026-08-11",
        "date64": "2026-08-11",
        "time32s": "01:02:03+00",
        "time32ms": "01:02:03.004+00",
        "time64us": "01:02:03.004+00",
        "time64ns": "01:02:03.004+00",
        "timestamp_s": "2026-08-11 01:02:03",
        "timestamp_ms": "2026-08-11 01:02:03.004",
        "timestamp_us": "2026-08-11 01:02:03.004",
        "timestamp_ns": "2026-08-11 01:02:03.004",
        "timestamp_tz": "2026-08-11 01:02:03+00",
    }


def test_fixture_manifest_types_come_from_post_parquet_arrow_schema(tmp_path: Path) -> None:
    source = tmp_path / "canonicalized-types.parquet"
    manifest, columns = _write_geoparquet(
        source,
        [Point(7.45, 46.95)],
        properties={
            "time": ("p_time", pa.array([clock_time(1, 2, 3)], type=pa.time32("s"))),
            "date": ("p_date", pa.array([date(2026, 8, 11)], type=pa.date64())),
            "timestamp": (
                "p_timestamp",
                pa.array([datetime(2026, 8, 11, 1, 2, 3)], type=pa.timestamp("s")),
            ),
        },
    )
    persisted = pq.read_schema(source)

    assert manifest.property_types == {
        display: str(persisted.field(physical).type) for display, physical in columns.items()
    }
    assert manifest.property_types == {
        "time": "time32[ms]",
        "date": "date32[day]",
        "timestamp": "timestamp[ms]",
    }


@pytest.mark.parametrize(
    "claimed_type",
    [
        "timestamp[ms, tz=UTC]",
        "timestamp[us, tz=Europe/Zurich]",
        "timestamp[ms, tz=Europe/Zurich]",
    ],
)
def test_timestamp_manifest_unit_and_timezone_must_match_parquet_logical_schema(
    tmp_path: Path, claimed_type: str
) -> None:
    source = tmp_path / "private-timestamp-mismatch.parquet"
    manifest, _ = _write_geoparquet(
        source,
        [Point(7.45, 46.95)],
        properties={
            "observed_at": (
                "p_observed_at",
                pa.array(
                    [datetime(2026, 8, 11, 1, 2, 3, tzinfo=UTC)],
                    type=pa.timestamp("us", tz="UTC"),
                ),
            )
        },
    )
    manifest = replace(
        manifest,
        property_types={"observed_at": claimed_type},
    )

    with pytest.raises(SourceInvalid, match="schema") as error:
        render_tile(SourceRef(str(source)), manifest, SWISS_TILE, RenderLimits())

    assert str(source) not in str(error.value)
    assert "private-timestamp-mismatch" not in str(error.value)
    assert error.value.__cause__ is None


def test_uint64_maximum_decodes_losslessly_as_string(tmp_path: Path) -> None:
    source = tmp_path / "uint64-maximum.parquet"
    maximum = 2**64 - 1
    manifest, _ = _write_geoparquet(
        source,
        [Point(7.45, 46.95)],
        properties={"unsigned": ("p_unsigned", pa.array([maximum], type=pa.uint64()))},
    )

    properties = _features(
        render_tile(SourceRef(str(source)), manifest, SWISS_TILE, RenderLimits())
    )[0]["properties"]

    assert properties == {"unsigned": str(maximum)}


def test_nested_arrow_property_type_remains_rejected(tmp_path: Path) -> None:
    source = tmp_path / "nested-property.parquet"
    manifest, _ = _write_geoparquet(
        source,
        [Point(7.45, 46.95)],
        properties={"nested": ("p_nested", pa.array([[1, 2]], type=pa.list_(pa.int32())))},
    )

    with pytest.raises(SourceInvalid, match="unsupported"):
        render_tile(SourceRef(str(source)), manifest, SWISS_TILE, RenderLimits())


def test_deterministic_point_thinning_keeps_lowest_feature_id(tmp_path: Path) -> None:
    source = tmp_path / "dense.parquet"
    points = [Point(7.45 + index * 1e-9, 46.95 + index * 1e-9) for index in range(20)]
    manifest, _ = _write_geoparquet(source, points, ids=list(reversed(range(20))))
    limits = RenderLimits(max_features_encoded=5)

    first = render_tile(SourceRef(str(source)), manifest, SWISS_TILE, limits)
    second = render_tile(SourceRef(str(source)), manifest, SWISS_TILE, limits)

    assert first == second
    assert [item["id"] for item in _features(first)] == [0]


@pytest.mark.parametrize(
    ("limit", "coordinates"),
    [
        (2, [100.0, 3900.0]),
        (5, [100.0, 2000.0, 3900.0]),
    ],
)
def test_point_thinning_respects_small_non_square_limits(
    tmp_path: Path, limit: int, coordinates: list[float]
) -> None:
    source = tmp_path / f"small-grid-{limit}.parquet"
    points = [_point_at_tile_units(SWISS_TILE, x, y) for x in coordinates for y in coordinates]
    manifest, _ = _write_geoparquet(source, points)

    features = _features(
        render_tile(
            SourceRef(str(source)),
            manifest,
            SWISS_TILE,
            RenderLimits(max_features_encoded=limit),
        )
    )

    assert 0 < len(features) <= limit


def test_default_point_limit_is_a_hard_bound_at_the_rounding_edge(tmp_path: Path) -> None:
    source = tmp_path / "default-grid-boundary.parquet"
    limit = 20_000
    old_grid = 4096.0 / math.sqrt(limit)
    positions = [(index + 0.5) * old_grid for index in range(141)]
    positions.append((141 * old_grid + 4096.0) / 2.0)
    assert len(positions) ** 2 == 20_164
    points = [_point_at_tile_units(SWISS_TILE, x, y) for x in positions for y in positions]
    manifest, _ = _write_geoparquet(source, points)
    limits = RenderLimits(
        max_features_encoded=limit,
        max_mvt_bytes=16 * 1024 * 1024,
    )

    first = render_tile(SourceRef(str(source)), manifest, SWISS_TILE, limits)
    second = render_tile(SourceRef(str(source)), manifest, SWISS_TILE, limits)

    assert first == second
    assert 0 < len(_features(first)) <= limit


@pytest.mark.parametrize("limit", [1, 2, 3, 5, 7, 19_999, 20_000, 20_001])
def test_integer_point_bin_plan_cannot_allocate_more_than_the_limit(limit: int) -> None:
    import tile_server.mvt as module

    x_bins, y_bins = module._point_grid_bins(limit)

    assert x_bins >= 1
    assert y_bins >= 1
    assert x_bins * y_bins <= limit


@pytest.mark.parametrize(
    "coord",
    [
        TileCoord(-1, 0, 0),
        TileCoord(17, 0, 0),
        TileCoord(8, -1, 0),
        TileCoord(8, 256, 0),
        TileCoord(8, 0, -1),
        TileCoord(8, 0, 256),
        TileCoord(True, 0, 0),
    ],
)
def test_rejects_zoom_and_coordinate_bounds(coord: TileCoord) -> None:
    with pytest.raises(InvalidTile):
        coord.validate(0, 16)


def test_rejects_manifest_minimum_zoom_too(tmp_path: Path) -> None:
    source = tmp_path / "zoom.parquet"
    manifest, _ = _write_geoparquet(source, [Point(7.45, 46.95)])
    manifest = replace(manifest, min_zoom=8)

    with pytest.raises(InvalidTile):
        render_tile(SourceRef(str(source)), manifest, TileCoord(7, 66, 45), RenderLimits())


@pytest.mark.parametrize(
    ("change", "match"),
    [
        (lambda geo: geo.pop("version"), "metadata"),
        (lambda geo: geo.__setitem__("version", "1.0.0"), "metadata"),
        (lambda geo: geo.__setitem__("primary_column", "missing"), "schema"),
        (
            lambda geo: geo["columns"]["geometry"].__setitem__("encoding", "geoarrow"),
            "metadata",
        ),
        (lambda geo: geo["columns"]["geometry"].pop("covering"), "covering"),
        (
            lambda geo: geo["columns"]["geometry"].__setitem__(
                "crs", {"id": {"authority": "EPSG", "code": 2056}}
            ),
            "CRS",
        ),
    ],
)
def test_rejects_malformed_geoparquet_metadata(tmp_path: Path, change: Any, match: str) -> None:
    source = tmp_path / "malformed.parquet"
    manifest, _ = _write_geoparquet(source, [Point(7.45, 46.95)], geo_mutation=change)

    with pytest.raises(SourceInvalid, match=match):
        render_tile(SourceRef(str(source)), manifest, SWISS_TILE, RenderLimits())


def test_rejects_geometry_type_name_that_only_contains_a_valid_name(tmp_path: Path) -> None:
    source = tmp_path / "substring-geometry-type.parquet"
    manifest, _ = _write_geoparquet(
        source,
        [Point(7.45, 46.95)],
        geo_mutation=lambda geo: geo["columns"]["geometry"].__setitem__(
            "geometry_types", ["DefinitelyNotAPoint"]
        ),
    )

    with pytest.raises(SourceInvalid, match="geometry family"):
        render_tile(SourceRef(str(source)), manifest, SWISS_TILE, RenderLimits())


@pytest.mark.parametrize(
    ("geometry_types", "expected"),
    [
        (["Point"], "point"),
        (["Point Z", "MultiPoint Z"], "point"),
        (["LineString", "MultiLineString"], "line"),
        (["Polygon Z", "MultiPolygon"], "polygon"),
        (["Point M"], None),
        (["Point ZM"], None),
        (["GeometryCollection"], None),
        (["Point", "Point"], None),
        (["Point", "LineString"], None),
    ],
)
def test_geometry_type_allow_list_matches_geoparquet_1_1(
    geometry_types: list[str], expected: str | None
) -> None:
    import tile_server.mvt as module

    assert module._geometry_family(geometry_types) == expected


def test_rejects_physical_schema_that_disagrees_with_manifest(tmp_path: Path) -> None:
    source = tmp_path / "schema.parquet"
    manifest, _ = _write_geoparquet(
        source,
        [Point(7.45, 46.95)],
        properties={"name": ("physical", pa.array(["Bern"]))},
    )
    manifest = replace(
        manifest,
        property_columns={"name": "other"},
        property_types={"name": "string"},
    )

    with pytest.raises(SourceInvalid, match="schema"):
        render_tile(SourceRef(str(source)), manifest, SWISS_TILE, RenderLimits())


def test_rejects_dataset_bbox_that_disagrees_with_manifest(tmp_path: Path) -> None:
    source = tmp_path / "bbox.parquet"
    manifest, _ = _write_geoparquet(source, [Point(7.45, 46.95)])
    manifest = replace(manifest, bbox=(6.0, 45.0, 6.1, 45.1))

    with pytest.raises(SourceInvalid, match="bbox"):
        render_tile(SourceRef(str(source)), manifest, SWISS_TILE, RenderLimits())


def test_row_feature_and_encoded_byte_limits_are_structural(tmp_path: Path) -> None:
    source = tmp_path / "limits.parquet"
    lines = [LineString([(7.440 + i * 0.001, 46.94), (7.445 + i * 0.001, 46.96)]) for i in range(3)]
    manifest, _ = _write_geoparquet(source, lines)

    with pytest.raises(TileTooLarge, match="rows"):
        render_tile(
            SourceRef(str(source)),
            manifest,
            SWISS_TILE,
            RenderLimits(max_rows_examined=2),
        )
    with pytest.raises(TileTooLarge, match="features"):
        render_tile(
            SourceRef(str(source)),
            manifest,
            SWISS_TILE,
            RenderLimits(max_features_encoded=2),
        )
    with pytest.raises(TileTooLarge, match="bytes"):
        render_tile(
            SourceRef(str(source)),
            manifest,
            SWISS_TILE,
            RenderLimits(max_mvt_bytes=1),
        )


def test_connection_is_one_thread_memory_bounded_and_request_private(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tile_server.mvt as module

    source = tmp_path / "settings.parquet"
    manifest, _ = _write_geoparquet(source, [Point(7.45, 46.95)])
    statements: list[str] = []
    real_new_connection = module._new_connection

    class Spy:
        def __init__(self) -> None:
            self.inner = real_new_connection()

        def execute(self, statement: str, parameters: Any = None) -> Any:
            statements.append(statement)
            if parameters is None:
                return self.inner.execute(statement)
            return self.inner.execute(statement, parameters)

        def close(self) -> None:
            self.inner.close()

        def interrupt(self) -> None:
            self.inner.interrupt()

    monkeypatch.setattr(module, "_new_connection", Spy)
    spill_parent = tmp_path / "spill"

    body = render_tile(
        SourceRef(str(source)),
        manifest,
        SWISS_TILE,
        RenderLimits(
            memory_bytes=64 * 1024 * 1024,
            max_spill_bytes=16 * 1024 * 1024,
            spill_directory=spill_parent,
        ),
    )

    _decode(body)
    joined = "\n".join(statements)
    assert "threads = 1" in joined
    assert "memory_limit" in joined and "67108864" in joined
    assert "max_temp_directory_size" in joined and "16777216" in joined
    assert "temp_directory" in joined
    assert spill_parent.is_dir() and list(spill_parent.iterdir()) == []


def test_timeout_and_keyboard_interruption_clean_spill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tile_server.mvt as module

    source = tmp_path / "timeout.parquet"
    manifest, _ = _write_geoparquet(source, [Point(7.45, 46.95)])
    spill_parent = tmp_path / "spill"

    with pytest.raises(module.RenderTimedOut):
        render_tile(
            SourceRef(str(source)),
            manifest,
            SWISS_TILE,
            RenderLimits(timeout_seconds=1e-9, spill_directory=spill_parent),
        )
    assert list(spill_parent.iterdir()) == []


def test_timeout_includes_connection_configuration_and_redacts_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tile_server.mvt as module

    source = tmp_path / "private-config-timeout.parquet"
    manifest, _ = _write_geoparquet(source, [Point(7.45, 46.95)])
    spill_parent = tmp_path / "spill"
    real_configure = module._configure_connection

    def slow_configure(*args: Any, **kwargs: Any) -> None:
        time.sleep(0.08)
        real_configure(*args, **kwargs)

    monkeypatch.setattr(module, "_configure_connection", slow_configure)
    monkeypatch.setattr(module, "_render_with_connection", lambda *args: b"")
    started = time.monotonic()

    with pytest.raises(module.RenderTimedOut) as error:
        render_tile(
            SourceRef(str(source)),
            manifest,
            SWISS_TILE,
            RenderLimits(timeout_seconds=0.01, spill_directory=spill_parent),
        )

    assert time.monotonic() - started < 0.3
    assert str(source) not in str(error.value)
    assert "private-config-timeout" not in str(error.value)
    assert error.value.__cause__ is None
    assert spill_parent.is_dir() and list(spill_parent.iterdir()) == []

    def interrupt(*args: Any, **kwargs: Any) -> bytes:
        del args, kwargs
        raise KeyboardInterrupt

    monkeypatch.setattr(module, "_render_with_connection", interrupt)
    with pytest.raises(KeyboardInterrupt):
        render_tile(
            SourceRef(str(source)),
            manifest,
            SWISS_TILE,
            RenderLimits(spill_directory=spill_parent),
        )
    assert list(spill_parent.iterdir()) == []


def test_forced_sql_error_is_redacted_and_cleans_spill(tmp_path: Path) -> None:
    source = tmp_path / "private-secret-name.parquet"
    manifest, _ = _write_geoparquet(source, [Point(7.45, 46.95)], family="point")
    table = pq.read_table(source)
    table = table.set_column(
        table.column_names.index("geometry"),
        "geometry",
        pa.array([b"not-wkb"], type=pa.binary()),
    )
    pq.write_table(table, source, compression="snappy")
    encoded = source.read_bytes()
    manifest = replace(
        manifest,
        source_sha256=sha256(encoded).hexdigest(),
        source_bytes=len(encoded),
    )
    spill_parent = tmp_path / "spill"

    with pytest.raises(SourceInvalid) as error:
        render_tile(
            SourceRef(str(source)),
            manifest,
            SWISS_TILE,
            RenderLimits(spill_directory=spill_parent),
        )

    assert str(source) not in str(error.value)
    assert "private-secret-name" not in str(error.value)
    assert error.value.__cause__ is None
    assert list(spill_parent.iterdir()) == []


def test_connection_close_failure_cannot_strand_private_spill(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tile_server.mvt as module

    source = tmp_path / "close.parquet"
    manifest, _ = _write_geoparquet(source, [Point(7.45, 46.95)])
    real_new_connection = module._new_connection

    class CloseFails:
        def __init__(self) -> None:
            self.inner = real_new_connection()

        def execute(self, statement: str, parameters: Any = None) -> Any:
            if parameters is None:
                return self.inner.execute(statement)
            return self.inner.execute(statement, parameters)

        def close(self) -> None:
            self.inner.close()
            raise RuntimeError("synthetic close failure")

        def interrupt(self) -> None:
            self.inner.interrupt()

    monkeypatch.setattr(module, "_new_connection", CloseFails)
    spill_parent = tmp_path / "spill"

    body = render_tile(
        SourceRef(str(source)),
        manifest,
        SWISS_TILE,
        RenderLimits(spill_directory=spill_parent),
    )

    _decode(body)
    assert list(spill_parent.iterdir()) == []


def test_runtime_has_no_install_and_loads_baked_extensions_without_home_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tile_server.mvt as module

    source_text = inspect.getsource(module)
    assert re.search(r"execute\(\s*[fr]?['\"]INSTALL\b", source_text, re.I) is None
    extension_root = Path.home() / ".duckdb" / "extensions"
    assert extension_root.is_dir()
    source = tmp_path / "offline.parquet"
    manifest, _ = _write_geoparquet(source, [Point(7.45, 46.95)])
    empty_home = tmp_path / "empty-home"
    empty_home.mkdir()
    monkeypatch.setenv("HOME", str(empty_home))
    monkeypatch.setenv("DUCKDB_EXTENSION_REPOSITORY", "http://127.0.0.1:9/unreachable")

    body = render_tile(
        SourceRef(str(source)),
        manifest,
        SWISS_TILE,
        RenderLimits(extension_directory=extension_root),
    )

    _decode(body)


@pytest.mark.parametrize(
    "value",
    [
        "https://example.com/source.parquet",
        "file:///tmp/source.parquet",
        "relative/source.parquet",
        "s3://bucket/object?signature=secret",
        "SELECT * FROM secrets",
    ],
)
def test_source_ref_accepts_only_absolute_local_or_private_s3_object(value: str) -> None:
    with pytest.raises(ValueError):
        SourceRef(value)


def test_source_ref_accepts_s3_object_without_browser_capability() -> None:
    source = SourceRef("s3://private-bucket/layers/token/source.parquet")
    assert source.is_s3


def test_s3_connection_seam_loads_only_baked_extensions_and_task_role_credentials(
    tmp_path: Path,
) -> None:
    import tile_server.mvt as module

    statements: list[str] = []

    class Recorder:
        def execute(self, statement: str, parameters: Any = None) -> Recorder:
            del parameters
            statements.append(statement)
            return self

    source = SourceRef("s3://private-bucket/layers/token/source.parquet")
    module._configure_connection(Recorder(), source, RenderLimits(), tmp_path, threading.Event())

    joined = "\n".join(statements)
    assert "LOAD spatial" in joined
    assert "LOAD json" not in joined
    assert "LOAD httpfs" in joined
    assert "LOAD aws" in joined
    assert "PROVIDER credential_chain" in joined
    assert source.uri not in joined
    assert re.search(r"execute\(\s*[fr]?['\"]INSTALL\b", inspect.getsource(module), re.I) is None


def test_s3_connection_uses_the_configured_private_endpoint(tmp_path: Path) -> None:
    """A local/private S3 endpoint must reach DuckDB, not only the boto3 store."""
    import tile_server.mvt as module

    statements: list[str] = []

    class Recorder:
        def execute(self, statement: str, parameters: Any = None) -> Recorder:
            del parameters
            statements.append(statement)
            return self

    module._configure_connection(
        Recorder(),
        SourceRef("s3://private-bucket/layers/token/source.parquet"),
        RenderLimits(s3_endpoint_url="http://127.0.0.1:59817"),
        tmp_path,
        threading.Event(),
    )

    secret = next(statement for statement in statements if statement.startswith("CREATE SECRET"))
    assert "ENDPOINT '127.0.0.1:59817'" in secret
    assert "USE_SSL false" in secret
    assert "URL_STYLE path" in secret


@pytest.mark.parametrize(
    "kwargs",
    [
        {"threads": 2},
        {"memory_bytes": 0},
        {"max_spill_bytes": 0},
        {"timeout_seconds": 0},
        {"max_rows_examined": 0},
        {"max_features_encoded": 0},
        {"max_mvt_bytes": 0},
    ],
)
def test_render_limits_are_strict_positive_and_one_thread(kwargs: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        RenderLimits(**kwargs)
