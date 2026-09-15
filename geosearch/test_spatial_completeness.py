"""Real park geometry and fault injections prevent plausible incomplete totals."""

import asyncio
import gzip
import json
from pathlib import Path

import pytest
from mcp import Client
from shapely.geometry import box, mapping

from .geometry import GeometryProcessingError, clip, measure, select_intersecting
from .server import build_server
from .swisstopo import IncompleteFeatureFetch, Swisstopo
from .test_server import RecordingArtifacts, StubBoundaries, StubIndex, StubSwisstopo


def parks():
    path = Path(__file__).parent / "fixtures/bern-parks-2026-09-11.json.gz"
    return json.loads(gzip.decompress(path.read_bytes()))


def test_live_parks_keep_eight_complete_source_geometries():
    data = parks()
    selected = select_intersecting(data["features"], data["boundary"])
    assert sorted(f["properties"]["objektnummer"] for f in selected) == [
        15,
        18,
        19,
        20,
        21,
        22,
        23,
        25,
    ]
    originals = {f["id"]: f for f in data["features"]}
    assert all(f is originals[f["id"]] for f in selected)
    clipped = clip(data["features"], data["boundary"])
    assert (
        len(clipped) == 7
    )  # repairs Gruyère; clipping still excludes the Pfyn-Finges sliver
    assert 23 in [f["properties"]["objektnummer"] for f in clipped]


def test_boundary_contact_is_selected_but_not_measured_as_an_area():
    boundary = [{"geometry": mapping(box(0, 0, 1, 1))}]
    neighbor = {"geometry": mapping(box(1, 0, 2, 1))}
    assert select_intersecting([neighbor], boundary) == [neighbor]
    assert clip([neighbor], boundary) == []


@pytest.mark.parametrize("operation", [clip, select_intersecting])
@pytest.mark.parametrize(
    "bad", [None, {"type": "Polygon", "coordinates": []}, {"type": "bad"}]
)
def test_unusable_feature_aborts_spatial_result(operation, bad):
    with pytest.raises(GeometryProcessingError):
        operation([{"geometry": bad}], [{"geometry": mapping(box(0, 0, 1, 1))}])


def test_measure_does_not_skip_unusable_geometry():
    with pytest.raises(GeometryProcessingError):
        measure([{"geometry": None}])


def test_failed_grid_cell_does_not_return_successful_cells():
    api = Swisstopo()

    async def cell(layer, bounds, lang, time):
        if bounds[0] == 0 and bounds[1] == 0:
            raise RuntimeError("injected network failure")
        return [{"id": str(bounds), "geometry": mapping(box(*bounds))}]

    api._fetch_cell = cell
    with pytest.raises(IncompleteFeatureFetch, match="1/4"):
        asyncio.run(
            api.fetch_features("ch.test", [0, 0, 2, 2], grid=2, time_instant="2026")
        )


def test_pagination_cap_does_not_return_a_partial_cell(monkeypatch):
    from . import swisstopo

    monkeypatch.setattr(swisstopo, "MAX_PAGES", 2)
    monkeypatch.setattr(swisstopo, "PAGE", 1)
    api = Swisstopo()

    async def get(url, params):
        return {
            "results": [{"id": params["offset"], "geometry": mapping(box(0, 0, 1, 1))}]
        }

    api._get = get
    with pytest.raises(IncompleteFeatureFetch, match="page limit"):
        asyncio.run(api._fetch_cell("ch.test", (0, 0, 2, 2), "de", "2026"))


def test_mcp_incomplete_fetch_has_no_count_or_result_handle():
    class FailedFetch(StubSwisstopo):
        async def fetch_features(self, *args, **kwargs):
            raise IncompleteFeatureFetch("One cell failed")

    async def run():
        server = build_server(
            StubIndex(), FailedFetch([]), RecordingArtifacts(), StubBoundaries()
        )
        async with Client(server) as client:
            response = await client.call_tool(
                "filter_features", {"layer_id": "ch.test", "bbox": [7, 46, 8, 47]}
            )
        data = response.structured_content
        assert data["complete"] is False
        assert "result_id" not in data
        assert "feature_count" not in data

    asyncio.run(run())


def test_mcp_selection_and_analysis_retain_scope():
    crossing = {
        "id": 1,
        "geometry": mapping(box(7.5, 46.5, 8.5, 47.5)),
        "properties": {},
    }
    artifacts = RecordingArtifacts()

    async def run():
        server = build_server(
            StubIndex(), StubSwisstopo([crossing]), artifacts, StubBoundaries()
        )
        async with Client(server) as client:
            response = await client.call_tool(
                "filter_features",
                {"layer_id": "ch.test", "place": "Bern", "spatial_mode": "intersects"},
            )
            data = response.structured_content
            assert data["selected_by"] == "kanton Bern"
            assert "clipped_to" not in data
            assert data["bbox"] == [7.5, 46.5, 8.5, 47.5]
            analysis = await client.call_tool(
                "analyze_features", {"result_id": data["result_id"]}
            )
            assert analysis.structured_content["spatial_mode"] == "intersects"
            assert analysis.structured_content["count"] == 1

    asyncio.run(run())
