"""Fetch less outside a named boundary; never turn a deadline into partial success."""

import asyncio

import httpx
import pytest
from mcp import Client
from shapely.geometry import box, mapping, shape

from .geometry import GeometryProcessingError, select_intersecting
from .server import build_server
from .swisstopo import LayerNotQueryable, Swisstopo
from .test_server import RecordingArtifacts, StubBoundaries, StubIndex


def test_disjoint_boundary_skips_cells_without_losing_whole_features():
    boundary = [
        {"geometry": mapping(box(0.1, 0.1, 0.9, 0.9))},
        {"geometry": mapping(box(3.1, 3.1, 3.9, 3.9))},
    ]
    features = [
        {"id": "crossing", "geometry": mapping(box(0.5, 0.5, 2.5, 2.5))},
        {"id": "island", "geometry": mapping(box(3.2, 3.2, 3.3, 3.3))},
        {"id": "outside", "geometry": mapping(box(1.2, 1.2, 1.3, 1.3))},
    ]
    requested = []
    api = Swisstopo()

    async def cell(layer, bounds, lang, time):
        requested.append(bounds)
        return [f for f in features if box(*bounds).intersects(shape(f["geometry"]))]

    api._fetch_cell = cell
    fetched = asyncio.run(
        api.fetch_features("ch.test", [0, 0, 4, 4], grid=4, time_instant="2026", boundary=boundary)
    )
    assert requested == [(0.0, 0.0, 1.0, 1.0), (3.0, 3.0, 4.0, 4.0)]
    assert select_intersecting(fetched, boundary) == select_intersecting(features, boundary)
    assert fetched[0] is features[0]  # Whole objects keep the source geometry.


def test_boundary_contacts_and_unscoped_bbox_coverage_are_preserved():
    requested = []
    api = Swisstopo()

    async def cell(layer, bounds, lang, time):
        requested.append(bounds)
        return []

    api._fetch_cell = cell
    asyncio.run(
        api.fetch_features(
            "ch.test",
            [0, 0, 2, 2],
            grid=2,
            time_instant="2026",
            boundary=[{"geometry": mapping(box(0.1, 0.1, 1.0, 0.9))}],
        )
    )
    assert requested == [(0.0, 0.0, 1.0, 1.0), (1.0, 0.0, 2.0, 1.0)]
    requested.clear()
    asyncio.run(api.fetch_features("ch.test", [0, 0, 2, 2], grid=2, time_instant="2026"))
    assert len(requested) == 4


@pytest.mark.parametrize("boundary", [[], [{"geometry": None}]])
def test_invalid_boundary_fails_before_fetching_any_cell(boundary):
    api = Swisstopo()

    async def unexpected(*args):
        pytest.fail("An invalid boundary must not fetch cells")

    api._fetch_cell = unexpected
    with pytest.raises(GeometryProcessingError):
        asyncio.run(
            api.fetch_features(
                "ch.test", [0, 0, 2, 2], grid=2, time_instant="2026", boundary=boundary
            )
        )


def test_mcp_fetch_deadline_cancels_pending_requests_without_partial_result(
    monkeypatch,
):
    from . import server

    monkeypatch.setattr(server, "FEATURE_FETCH_TIMEOUT_SECONDS", 0.05)

    async def run():
        active = 0
        cancelled = 0
        requests = 0

        async def respond(request):
            nonlocal active, cancelled, requests
            requests += 1
            if requests == 1:
                return httpx.Response(
                    200,
                    json={
                        "results": [
                            {
                                "id": 1,
                                "geometry": mapping(box(7, 46, 7.1, 46.1)),
                                "properties": {},
                            }
                        ]
                    },
                )
            active += 1
            try:
                await asyncio.Event().wait()
            finally:
                active -= 1
                cancelled += 1

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            api = Swisstopo(client)
            api._layers_config = {"de": {"ch.test": {"timeEnabled": False}}}
            artifacts = RecordingArtifacts()
            mcp_server = build_server(StubIndex(), api, artifacts, StubBoundaries())
            async with Client(mcp_server) as mcp:
                response = await mcp.call_tool(
                    "filter_features", {"layer_id": "ch.test", "place": "Bern"}
                )
            data = response.structured_content
            assert data["complete"] is False
            assert "display_catalog_layer" in data["error"]
            assert "result_id" not in data
            assert "feature_count" not in data
            assert artifacts.calls == []
            assert active == 0
            assert cancelled > 0
            assert requests < 64  # Queued cells were cancelled too.

    asyncio.run(run())


def test_caller_cancellation_propagates_and_drains_requests():
    async def run():
        active = 0
        started = asyncio.Event()

        async def respond(request):
            nonlocal active
            active += 1
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                active -= 1

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            api = Swisstopo(client)
            task = asyncio.create_task(
                api.fetch_features("ch.test", [7, 46, 8, 47], time_instant="2026")
            )
            await asyncio.wait_for(started.wait(), timeout=1)
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert active == 0

    asyncio.run(run())


@pytest.mark.parametrize(
    "body,exception",
    [
        ("No Vector Table was found for ch.test", LayerNotQueryable),
        ("Invalid geometry parameter", httpx.HTTPStatusError),
    ],
)
def test_only_missing_vector_table_is_classified_as_not_queryable(body, exception):
    async def run():
        transport = httpx.MockTransport(lambda request: httpx.Response(400, text=body))
        async with httpx.AsyncClient(transport=transport) as client:
            api = Swisstopo(client)
            with pytest.raises(exception):
                await api._fetch_cell("ch.test", (7, 46, 8, 47), "de", None)

    asyncio.run(run())
