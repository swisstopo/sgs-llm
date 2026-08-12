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

    async def fetch_features(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return self.features


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
