"""MCP-level contracts for feature limits and displayed artifact formats."""

from __future__ import annotations

from typing import Any

import pytest
from mcp import Client

from .server import build_server

pytestmark = pytest.mark.anyio


def _point(index: int, *, keep: bool = True, x: float = 7.0) -> dict[str, Any]:
    return {
        "type": "Feature",
        "id": index,
        "geometry": {"type": "Point", "coordinates": [x, 46.0]},
        "properties": {"name": "keep" if keep else "drop", "index": index},
    }


class StubIndex:
    def division_by_name(
        self, name: str, kind: str | None = None
    ) -> dict[str, Any] | None:
        if name != "Bern":
            return None
        return {
            "name": "Bern",
            "kind": kind or "kanton",
            "s3_key": "layers/divisions/kanton/bern.geojson",
            "feature_count": 1,
            "bbox": [7.0, 46.0, 8.0, 47.0],
        }


class StubSwisstopo:
    def __init__(self, features: list[dict[str, Any]]) -> None:
        self.features = features
        self.fetch_kwargs: dict[str, Any] = {}

    async def fetch_features(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        self.fetch_kwargs = kwargs
        return self.features

    async def geocode_location(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [{
            "location_ref": "address:1",
            "kind": "address",
            "label": "Seftigenstrasse 264, 3084 Wabern",
            "coordinates": {
                "wgs84": {"longitude": 7.45135, "latitude": 46.92794},
                "lv95": {"easting": 2600968.75, "northing": 1197427.0},
            },
            "match_quality": "exact",
            "related_features": [],
        }]

    async def identify_at_point(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        feature = {
            "feature_ref": {"layer_id": "ch.test.oereb", "feature_id": "865116"},
            "layer_name": "ÖREB parcel",
            "properties": {
                "egris_egrid": "CH669746359158",
                "oereb_extract_pdf": "https://example.test/extract.pdf",
            },
            "external_links": [{
                "field": "oereb_extract_pdf",
                "kind": "pdf",
                "label": "oereb extract pdf",
                "url": "https://example.test/extract.pdf",
            }],
        }
        if kwargs.get("return_geometry"):
            feature["geometry"] = {"type": "Point", "coordinates": [7.45135, 46.92794]}
        return [feature]

    async def describe_layer(self, layer_id: str, lang: str) -> dict[str, Any] | None:
        if layer_id == "missing":
            return None
        return {
            "layer_id": layer_id,
            "title": "ÖREB",
            "fields": [{"name": "oereb_extract_pdf", "type": "VARCHAR"}],
            "queryable": True,
            "displayable": True,
        }


class StubBoundaries:
    def get_geojson(self, key: str) -> dict[str, Any]:
        return {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "id": "bern",
                    "properties": {"name": "Bern"},
                    "geometry": {
                        "type": "Polygon",
                        "coordinates": [
                            [
                                [7.0, 46.0],
                                [8.0, 46.0],
                                [8.0, 47.0],
                                [7.0, 47.0],
                                [7.0, 46.0],
                            ]
                        ],
                    },
                }
            ],
        }


class RecordingArtifacts:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[tuple[str, list[dict[str, Any]]]] = []

    async def publish_geoparquet(
        self, name: str, features: list[dict[str, Any]]
    ) -> str | None:
        self.calls.append((name, features))
        return None if self.fail else f"https://data.test/{name}"


async def _call(
    features: list[dict[str, Any]],
    tool: str,
    arguments: dict[str, Any],
    *,
    artifacts: RecordingArtifacts | None = None,
) -> dict[str, Any]:
    server = build_server(
        StubIndex(),
        StubSwisstopo(features),
        artifacts or RecordingArtifacts(),
        StubBoundaries(),
    )
    async with Client(server) as client:
        result = await client.call_tool(tool, arguments)
    assert isinstance(result.structured_content, dict)
    return result.structured_content


async def test_phase_one_exposes_the_intended_ten_tools() -> None:
    server = build_server(
        StubIndex(), StubSwisstopo([]), RecordingArtifacts(), StubBoundaries()
    )
    async with Client(server) as client:
        tools = await client.list_tools()

    assert {tool.name for tool in tools.tools} == {
        "search_layers",
        "search_locations",
        "geocode_location",
        "describe_layer",
        "identify_at_point",
        "filter_features",
        "analyze_features",
        "display_division",
        "display_catalog_layer",
        "display_layer",
    }


async def test_exactly_one_hundred_thousand_features_are_accepted() -> None:
    data = await _call(
        [_point(index) for index in range(100_000)],
        "filter_features",
        {"layer_id": "ch.test", "bbox": [7.0, 46.0, 8.0, 47.0]},
    )

    assert data["feature_count"] == 100_000
    assert data["result_id"].startswith("fs_")
    assert "error" not in data


async def test_one_hundred_thousand_and_one_is_rejected_without_a_handle() -> None:
    data = await _call(
        [_point(index) for index in range(100_001)],
        "filter_features",
        {"layer_id": "ch.test", "bbox": [7.0, 46.0, 8.0, 47.0]},
    )

    assert data == {
        "error": "Result contains more than 100,000 features. Narrow the place, area, or dataset.",
        "feature_count": 100_001,
        "limit": 100_000,
    }
    assert "result_id" not in data


async def test_limit_is_checked_after_the_text_filter() -> None:
    features = [_point(index, keep=False) for index in range(100_001)] + [
        _point(100_001)
    ]

    data = await _call(
        features,
        "filter_features",
        {
            "layer_id": "ch.test",
            "bbox": [7.0, 46.0, 8.0, 47.0],
            "contains": "keep",
        },
    )

    assert data["feature_count"] == 1
    assert "result_id" in data


async def test_limit_is_checked_after_boundary_clipping(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from . import server as module

    features = [_point(index) for index in range(100_001)]
    clipped = features[:2]
    monkeypatch.setattr(module, "clip", lambda candidates, boundary: clipped)

    data = await _call(
        features,
        "filter_features",
        {"layer_id": "ch.test", "place": "Bern", "place_kind": "kanton"},
    )

    assert data["feature_count"] == 2
    assert "result_id" in data
    assert data["clipped_to"] == "kanton Bern"


async def test_empty_named_result_still_confirms_the_boundary_scope() -> None:
    data = await _call(
        [],
        "filter_features",
        {"layer_id": "ch.test", "place": "Bern", "place_kind": "kanton"},
    )

    assert data["feature_count"] == 0
    assert data["clipped_to"] == "kanton Bern"


async def test_named_result_over_the_limit_keeps_its_boundary_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from . import server as module

    features = [_point(index) for index in range(100_001)]
    monkeypatch.setattr(module, "clip", lambda candidates, boundary: candidates)

    data = await _call(
        features,
        "filter_features",
        {"layer_id": "ch.test", "place": "Bern", "place_kind": "kanton"},
    )

    assert data["feature_count"] == 100_001
    assert data["clipped_to"] == "kanton Bern"
    assert "error" in data


async def test_display_layer_publishes_geoparquet() -> None:
    features = [_point(1)]
    artifacts = RecordingArtifacts()
    server = build_server(
        StubIndex(), StubSwisstopo(features), artifacts, StubBoundaries()
    )
    async with Client(server) as client:
        fetched = await client.call_tool(
            "filter_features", {"layer_id": "ch.test", "bbox": [7, 46, 8, 47]}
        )
        result_id = fetched.structured_content["result_id"]
        shown = await client.call_tool(
            "display_layer", {"result_id": result_id, "name": "Test layer"}
        )

    assert shown.structured_content["layer"]["format"] == "parquet"
    assert shown.structured_content["layer"]["url"].endswith(f"/{result_id}.parquet")
    assert artifacts.calls == [(f"{result_id}.parquet", features)]


async def test_display_division_converts_the_baked_geojson_to_geoparquet() -> None:
    artifacts = RecordingArtifacts()
    server = build_server(StubIndex(), StubSwisstopo([]), artifacts, StubBoundaries())
    async with Client(server) as client:
        shown = await client.call_tool(
            "display_division", {"name": "Bern", "kind": "kanton"}
        )

    layer = shown.structured_content["layer"]
    assert layer["format"] == "parquet"
    assert layer["url"].endswith("/division-kanton-Bern.parquet")
    assert artifacts.calls[0][0] == "division-kanton-Bern.parquet"
    assert artifacts.calls[0][1][0]["properties"]["name"] == "Bern"


@pytest.mark.parametrize("tool", ["display_layer", "display_division"])
async def test_publication_failure_is_a_semantic_error(tool: str) -> None:
    artifacts = RecordingArtifacts(fail=True)
    server = build_server(
        StubIndex(), StubSwisstopo([_point(1)]), artifacts, StubBoundaries()
    )
    async with Client(server) as client:
        if tool == "display_layer":
            fetched = await client.call_tool(
                "filter_features", {"layer_id": "ch.test", "bbox": [7, 46, 8, 47]}
            )
            arguments = {
                "result_id": fetched.structured_content["result_id"],
                "name": "Test",
            }
        else:
            arguments = {"name": "Bern", "kind": "kanton"}
        shown = await client.call_tool(tool, arguments)

    assert shown.structured_content == {"error": "Could not publish the layer."}


async def test_geocode_reference_can_be_used_for_full_point_identify() -> None:
    api = StubSwisstopo([])
    server = build_server(StubIndex(), api, RecordingArtifacts(), StubBoundaries())
    async with Client(server) as client:
        geocoded = await client.call_tool(
            "geocode_location", {"query": "Seftigenstrasse 264 Wabern", "origins": ["address"]}
        )
        location_ref = geocoded.structured_content["locations"][0]["location_ref"]
        identified = await client.call_tool(
            "identify_at_point",
            {"location_ref": location_ref, "layer_ids": ["ch.test.oereb"]},
        )

    assert identified.structured_content["feature_count"] == 1
    feature = identified.structured_content["features"][0]
    assert feature["properties"]["oereb_extract_pdf"].endswith("extract.pdf")
    assert feature["external_links"][0]["kind"] == "pdf"


async def test_geocode_result_can_be_displayed_as_a_personalized_point() -> None:
    artifacts = RecordingArtifacts()
    server = build_server(StubIndex(), StubSwisstopo([]), artifacts, StubBoundaries())
    async with Client(server) as client:
        geocoded = await client.call_tool(
            "geocode_location", {"query": "Seftigenstrasse 264, 3084 Wabern"}
        )
        location = geocoded.structured_content["locations"][0]
        shown = await client.call_tool(
            "display_layer",
            {"result_id": location["result_id"], "name": location["label"]},
        )

    assert location["display_scope"] == "geocoded_point"
    assert shown.structured_content["layer"]["geometry_type"] == "point"
    assert shown.structured_content["layer"]["feature_count"] == 1
    assert shown.structured_content["layer"]["bbox"] == [
        7.45135,
        46.92794,
        7.45135,
        46.92794,
    ]


async def test_point_identify_geometry_produces_a_personalized_display_result() -> None:
    api = StubSwisstopo([])
    artifacts = RecordingArtifacts()
    server = build_server(StubIndex(), api, artifacts, StubBoundaries())
    async with Client(server) as client:
        geocoded = await client.call_tool(
            "geocode_location", {"query": "Seftigenstrasse 264 Wabern"}
        )
        location_ref = geocoded.structured_content["locations"][0]["location_ref"]
        identified = await client.call_tool(
            "identify_at_point",
            {
                "location_ref": location_ref,
                "layer_ids": ["ch.test.oereb"],
                "return_geometry": True,
            },
        )
        shown = await client.call_tool(
            "display_layer",
            {
                "result_id": identified.structured_content["result_id"],
                "name": "ÖREB parcel result",
            },
        )

    assert identified.structured_content["display_feature_count"] == 1
    assert identified.structured_content["result_id"].startswith("fs_")
    assert "geometry" not in identified.structured_content["features"][0]
    assert shown.structured_content["layer"]["feature_count"] == 1
    assert shown.structured_content["layer"]["bbox"] == [7.45135, 46.92794, 7.45135, 46.92794]
    assert artifacts.calls[0][1][0]["properties"]["egris_egrid"] == "CH669746359158"


async def test_describe_layer_exposes_complete_schema() -> None:
    data = await _call([], "describe_layer", {"layer_id": "ch.test.oereb"})

    assert data["layer"]["fields"][0]["name"] == "oereb_extract_pdf"
    assert data["layer"]["queryable"] is True


async def test_structured_filters_and_time_are_applied_before_caching() -> None:
    api = StubSwisstopo([
        {**_point(1), "properties": {"category": "high", "value": 12}},
        {**_point(2), "properties": {"category": "low", "value": 3}},
    ])
    server = build_server(StubIndex(), api, RecordingArtifacts(), StubBoundaries())
    async with Client(server) as client:
        fetched = await client.call_tool(
            "filter_features",
            {
                "layer_id": "ch.test",
                "bbox": [7, 46, 8, 47],
                "time": "2025",
                "filters": [{"field": "value", "operator": "greater_than", "value": 10}],
            },
        )

    assert fetched.structured_content["feature_count"] == 1
    assert api.fetch_kwargs["time_instant"] == "2025"


async def test_analyze_features_groups_and_computes_numeric_statistics() -> None:
    features = [
        {**_point(1), "properties": {"category": "high", "value": 12}},
        {**_point(2), "properties": {"category": "high", "value": 8}},
        {**_point(3), "properties": {"category": "low", "value": None}},
    ]
    server = build_server(
        StubIndex(), StubSwisstopo(features), RecordingArtifacts(), StubBoundaries()
    )
    async with Client(server) as client:
        fetched = await client.call_tool(
            "filter_features", {"layer_id": "ch.test", "bbox": [7, 46, 8, 47]}
        )
        result_id = fetched.structured_content["result_id"]
        grouped = await client.call_tool(
            "analyze_features",
            {"result_id": result_id, "operation": "group_by", "field": "category"},
        )
        stats = await client.call_tool(
            "analyze_features",
            {"result_id": result_id, "operation": "numeric_statistics", "field": "value"},
        )

    assert grouped.structured_content["groups"][0] == {"value": "high", "count": 2}
    assert stats.structured_content["statistics"] == {
        "numeric_count": 2,
        "min": 8.0,
        "max": 12.0,
        "mean": 10.0,
        "sum": 20.0,
    }
    assert stats.structured_content["missing_values"] == 1
