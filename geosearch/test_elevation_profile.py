"""Profile service contract, route selection and a fetched-result-to-map chain."""

import asyncio
import copy
import json
import math
from urllib.parse import parse_qs

import httpx
import pytest
from mcp import Client
from pyproj import Transformer

from .elevation import PROFILE_URL, project_route, select_route, summarize_profile
from .profile_tool import register_profile_tool
from .results import ResultCache
from .server import build_server
from .swisstopo import Swisstopo
from .test_server import RecordingArtifacts, StubBoundaries, StubIndex

LINE = {
    "type": "LineString",
    "coordinates": [[7.1, 46.8], [7.101, 46.801], [7.102, 46.802]],
}
FEATURE = {"id": 20, "geometry": LINE, "properties": {"name": "Test route"}}


def service_response(route):
    coords = route["coordinates"]
    distances = [0]
    for a, b in zip(coords, coords[1:]):
        distances.append(distances[-1] + math.dist(a, b))
    return [
        {"dist": d, "easting": p[0], "northing": p[1], "alts": {"COMB": h}}
        for p, d, h in zip(coords, distances, [100, 160, 140])
    ]


def test_projected_request_and_sampled_measurements():
    route = project_route(LINE)
    inverse = Transformer.from_crs(2056, 4326, always_xy=True)
    assert inverse.transform(*route["coordinates"][0]) == pytest.approx(
        LINE["coordinates"][0], abs=1e-7
    )
    result = summarize_profile(service_response(route), route)
    assert result["ascent_m"] == 60
    assert result["descent_m"] == 20
    assert result["min_elevation_m"] == 100
    assert result["max_elevation_m"] == 160
    assert result["sample_count"] == 3


@pytest.mark.parametrize("payload", [{"error": "unavailable"}, [], [{}], [None, None]])
def test_malformed_or_missing_profile_is_not_a_zero_total(payload):
    with pytest.raises(ValueError):
        summarize_profile(payload, project_route(LINE))


@pytest.mark.parametrize(
    "failure", ["nan", "missing_height", "missing_endpoint", "reversed", "shortened"]
)
def test_incomplete_and_invalid_measurements_are_rejected(failure):
    route = project_route(LINE)
    rows = service_response(route)
    if failure == "nan":
        rows[1]["alts"]["COMB"] = float("nan")
    if failure == "missing_height":
        rows[1]["alts"]["COMB"] = None
    if failure == "missing_endpoint":
        rows.pop()
    if failure == "reversed":
        rows[1]["dist"] = -1
    if failure == "shortened":
        rows[-1]["dist"] -= 20
    with pytest.raises(ValueError):
        summarize_profile(rows, route)


@pytest.mark.parametrize(
    "coordinates",
    [
        [],
        [[7, 46]],
        [[7, 46]] * 2,
        [[float("inf"), 46], [7, 46]],
        [[2600000, 1200000], [2600100, 1200100]],
        [[7, 46]] * 5001,
    ],
)
def test_invalid_or_oversized_routes_fail_before_network(coordinates):
    with pytest.raises(ValueError):
        project_route({"type": "LineString", "coordinates": coordinates})


def test_multiline_selection_preserves_parts_without_joining():
    feature = {
        **FEATURE,
        "geometry": {
            "type": "MultiLineString",
            "coordinates": (LINE["coordinates"], [[8, 47], [8.1, 47.1]]),
        },
    }
    with pytest.raises(ValueError, match="part_index"):
        select_route([feature], None, None)
    chosen, scope = select_route([feature], None, 1)
    assert chosen["geometry"]["coordinates"] == [[8, 47], [8.1, 47.1]]
    assert scope["part_count"] == 2
    assert scope["scope"] == "selected line part"


def test_connector_posts_lv95_geometry_with_explicit_sampling():
    seen = []

    def handle(request):
        assert request.method == "POST"
        assert str(request.url) == PROFILE_URL
        form = parse_qs(request.content.decode())
        assert form["sr"] == ["2056"]
        assert form["nb_points"] == ["20"]
        route = json.loads(form["geom"][0])
        assert route["coordinates"][0][0] > 2_000_000
        seen.append(request)
        return httpx.Response(200, json=service_response(route))

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            result = await Swisstopo(client).elevation_profile(LINE, samples=20)
            assert result["complete"] is True
            with pytest.raises(ValueError, match="samples"):
                await Swisstopo(client).elevation_profile(LINE, samples=201)

    asyncio.run(run())
    assert len(seen) == 1


def test_mcp_fetch_profile_and_display_use_the_same_selected_route():
    class API(Swisstopo):
        async def fetch_features(self, *args, **kwargs):
            return [FEATURE, {**FEATURE, "id": 21}]

    seen = []

    def handle(request):
        seen.append(request)
        route = json.loads(parse_qs(request.content.decode())["geom"][0])
        return httpx.Response(200, json=service_response(route))

    async def run():
        artifacts = RecordingArtifacts()
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            server = build_server(StubIndex(), API(http), artifacts, StubBoundaries())
            async with Client(server) as client:
                fetched = await client.call_tool(
                    "filter_features", {"layer_id": "ch.routes", "bbox": [7, 46, 8, 47]}
                )
                source = fetched.structured_content["result_id"]
                choice = await client.call_tool(
                    "elevation_profile", {"result_id": source}
                )
                assert choice.structured_content["candidate_count"] == 2
                assert not seen
                profiled = await client.call_tool(
                    "elevation_profile", {"result_id": source, "feature_index": 1}
                )
                data = profiled.structured_content
                assert data["ascent_m"] == 60
                assert data["source_result_id"] == source
                assert data["result_id"] != source
                displayed = await client.call_tool(
                    "display_layer",
                    {"result_id": data["result_id"], "name": "Selected route"},
                )
                assert displayed.structured_content["layer"]["feature_count"] == 1
                assert artifacts.calls[0][1] == [{**FEATURE, "id": 21}]

    asyncio.run(run())


def test_unavailable_service_does_not_create_a_route_result():
    from mcp.server import MCPServer

    cache = ResultCache()
    entry = cache.put("ch.routes", "route", [copy.deepcopy(FEATURE)])

    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda r: httpx.Response(503))
        ) as http:
            server = MCPServer(name="test")
            register_profile_tool(server, Swisstopo(http), cache)
            async with Client(server) as client:
                response = await client.call_tool(
                    "elevation_profile", {"result_id": entry.result_id}
                )
                assert response.structured_content["complete"] is False
                assert "result_id" not in response.structured_content

    asyncio.run(run())


def test_dense_service_profile_keeps_all_measurements_in_totals():
    # Observed HTTP 203: the live service retains 421 vertices despite nb_points=100.
    # Do not reject that valid profile or compute ascent from only the reduced series.
    coords = [[2600000 + i, 1200000] for i in range(421)]
    route = {"type": "LineString", "coordinates": coords}
    rows = [
        {"dist": i, "easting": p[0], "northing": p[1], "alts": {"COMB": 100 + i % 2}}
        for i, p in enumerate(coords)
    ]
    result = summarize_profile(rows, route)
    assert result["sample_count"] == 421
    assert result["returned_sample_count"] == 200
    assert result["samples_summarized"] is True
    assert result["ascent_m"] == 210
    assert result["descent_m"] == 210
    assert result["samples"][0]["distance_m"] == 0
    assert result["samples"][-1]["distance_m"] == 420
