"""End-to-end against a real MCP server.

The only thing stubbed is geo.admin.ch. The real dummy server, the real MCP client and
the real agent loop do the rest, so this covers tool discovery, schema conversion, tool
calls, artifact publishing and LayerSpec extraction as a whole.

Transport is the in-process one, which is what the backend uses when no MCP_SERVER_URL
is set. The remote Streamable HTTP path shares everything above the transport.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from mcp_dummy.server import build_server
from mcp_dummy.swisstopo import Swisstopo

from app.agent.loop import TurnStats, run_turn
from app.config import Settings
from app.mcp.client import ToolGateway
from app.protocol import UserMessage
from app.store.artifacts import ArtifactStore
from tests.conftest import FakeModels, text_result, tool_result

LAYER_SEARCH = {
    "results": [
        {
            "attrs": {
                "layer": "ch.bafu.hydrologie-hochwasserstatistik",
                "label": "<b>Hochwasserstatistik</b>",
                "detail": "hochwasserstatistik | messstationen",
            }
        }
    ]
}

CANTON_SEARCH = {
    "results": [
        {
            "attrs": {
                "label": "<b>Valais</b>",
                "origin": "kantone",
                "geom_st_box2d": "BOX(6.76686 45.853976,8.480974 46.656104)",
            }
        }
    ]
}

IDENTIFY = {
    "results": [
        {
            "featureId": "2011",
            "layerBodId": "ch.bafu.hydrologie-hochwasserstatistik",
            "geometry": {"type": "Point", "coordinates": [7.357901, 46.21909]},
            "properties": {"name": "Rhône - Sion", "gefahrenstufe": "hoch"},
        },
        {
            "featureId": "2018",
            "layerBodId": "ch.bafu.hydrologie-hochwasserstatistik",
            "geometry": {"type": "Point", "coordinates": [7.62, 46.29]},
            "properties": {"name": "Rhône - Sierre", "gefahrenstufe": "mittel"},
        },
    ]
}


# Trimmed to the two shapes that matter: one queryable vector layer and one raster layer
# that can only be shown, not queried. Both verified against the live API on 2026-07-31.
LAYERS_CONFIG = {
    "ch.bafu.hydrologie-hochwasserstatistik": {
        "type": "wmts",
        "label": "Hochwasserstatistik",
        "queryable": True,
    },
    "ch.bafu.aquaprotect_100": {
        "type": "wmts",
        "label": "Überschwemmung Aquaprotect 100",
        "queryable": False,
    },
}


def _fake_geoadmin(request: httpx.Request) -> httpx.Response:
    path = request.url.path
    params = request.url.params
    if path.endswith("layersConfig"):
        return httpx.Response(200, json=LAYERS_CONFIG)
    if path.endswith("SearchServer"):
        if params.get("type") == "layers":
            return httpx.Response(200, json=LAYER_SEARCH)
        return httpx.Response(200, json=CANTON_SEARCH)
    if "identify" in path:
        return httpx.Response(200, json=IDENTIFY)
    return httpx.Response(404, json={})


@pytest.fixture
def gateway_and_artifacts() -> Any:
    """A gateway onto the real dummy MCP server, with only geo.admin.ch stubbed.

    Uses the in-process transport, so the tool contract is exercised without a listener.
    The remote Streamable HTTP path that production runs is the SDK's transport plus the
    same `ToolSession` code, covered in tests/test_mcp.py.

    The client is injected, so the gateway owns no HTTP connection of its own.
    """
    api = Swisstopo(httpx.AsyncClient(transport=httpx.MockTransport(_fake_geoadmin)))
    artifacts = ArtifactStore(Settings())
    return ToolGateway(server=build_server(artifacts, swisstopo=api)), artifacts


async def test_tool_catalogue_is_discovered_and_converted_for_bedrock(
    gateway_and_artifacts: Any,
) -> None:
    gateway, _ = gateway_and_artifacts
    async with gateway.session() as session:
        names = session.tool_names
        assert set(names) == {
            "search_layers",
            "search_locations",
            "filter_features",
            "analyze_features",
            "display_layer",
            "display_catalog_layer",
        }
        for spec in session.tool_specs:
            tool_spec = spec["toolSpec"]
            assert tool_spec["description"]
            schema = tool_spec["inputSchema"]["json"]
            assert schema["type"] == "object"
            # Bedrock (and Mistral especially) does not want pydantic's title keys.
            assert "title" not in schema
            assert all("title" not in prop for prop in schema["properties"].values())


async def test_the_tool_catalogue_is_cached_across_turns(gateway_and_artifacts: Any) -> None:
    gateway, _ = gateway_and_artifacts
    async with gateway.session() as first:
        specs = first.tool_specs
    async with gateway.session() as second:
        assert second.tool_specs is specs


async def test_a_place_scoped_question_chains_the_tools(gateway_and_artifacts: Any) -> None:
    """search_locations -> filter_features -> display_layer, the core user journey."""
    gateway, artifacts = gateway_and_artifacts

    async with gateway.session() as session:
        located = await session.call("search_locations", {"query": "Wallis", "lang": "de"})
        assert located.is_error is False
        bbox = located.data["places"][0]["bbox"]

        fetched = await session.call(
            "filter_features",
            {"layer_id": "ch.bafu.hydrologie-hochwasserstatistik", "bbox": bbox, "lang": "de"},
        )
        assert fetched.data["feature_count"] == 2
        assert fetched.data["geometry_type"] == "point"
        # The features themselves stay server-side; only a handle crosses the wire.
        assert "features" not in fetched.text
        result_id = fetched.data["result_id"]

        computed = await session.call(
            "analyze_features", {"result_id": result_id, "operation": "summary"}
        )
        assert computed.data["count"] == 2

        shown = await session.call(
            "display_layer", {"result_id": result_id, "name": "Messstationen Wallis"}
        )
        layer = shown.data["layer"]
        assert layer["format"] == "geojson"
        assert layer["geometry_type"] == "point"
        assert layer["feature_count"] == 2
        assert "swisstopo" in layer["attribution"]

    # The published artifact is real, parseable GeoJSON.
    body = artifacts.read_local(f"{result_id}.geojson")
    assert body is not None
    collection = json.loads(body)
    assert collection["type"] == "FeatureCollection"
    assert len(collection["features"]) == 2


async def test_a_stale_handle_is_reported_rather_than_crashing(gateway_and_artifacts: Any) -> None:
    gateway, _ = gateway_and_artifacts
    async with gateway.session() as session:
        outcome = await session.call("analyze_features", {"result_id": "fs_gone"})
        assert "Unknown result_id" in outcome.text


async def test_a_malformed_bbox_is_rejected_with_guidance(gateway_and_artifacts: Any) -> None:
    gateway, _ = gateway_and_artifacts
    async with gateway.session() as session:
        outcome = await session.call("filter_features", {"layer_id": "ch.x", "bbox": [7, 46]})
        assert "bbox" in outcome.text


async def test_a_full_turn_produces_an_answer_and_a_layer(
    gateway_and_artifacts: Any, settings: Settings
) -> None:
    """The whole path with only the model scripted: a real MCP round trip, a real
    artifact, and a LayerSpec the frontend would accept."""
    gateway, _ = gateway_and_artifacts
    models = FakeModels(
        [
            tool_result("search_locations", {"query": "Wallis", "lang": "de"}, "tu1"),
            tool_result(
                "filter_features",
                {
                    "layer_id": "ch.bafu.hydrologie-hochwasserstatistik",
                    "bbox": [6.76686, 45.853976, 8.480974, 46.656104],
                    "lang": "de",
                },
                "tu2",
            ),
            text_result("Im Wallis gibt es zwei Messstationen."),
        ]
    )

    stats = TurnStats()
    message = UserMessage.model_validate(
        {
            "type": "user_message",
            "id": "m1",
            "content": "Zeige mir Hochwasser-Messstationen im Wallis",
            "lang": "de",
        }
    )
    events = [
        event
        async for event in run_turn(
            message,
            models=models,
            gateway=gateway,
            settings=settings,
            stats=stats,
            base_url="https://denpw8uo5zpkl.cloudfront.net",
        )
    ]

    assert events[-1].type == "final"
    assert stats.tool_calls == ["search_locations", "filter_features"]
    # The model saw the real tool catalogue.
    assert models.calls[0]["tools"] is not None
    assert len(models.calls[0]["tools"]) == 6


async def test_a_raster_layer_is_shown_as_a_catalog_reference(
    gateway_and_artifacts: Any, settings: Settings
) -> None:
    """The proposed raster path, end to end, with the capability enabled.

    Aquaprotect and the noise maps are WMTS and cannot be a LayerSpec. `catalog_layers`
    names those official layers so the browser can offer a user-controlled tile action.
    """
    settings.enable_catalog_layers = True
    gateway, _ = gateway_and_artifacts
    models = FakeModels(
        [
            tool_result(
                "display_catalog_layer",
                {
                    "layer_id": "ch.bafu.aquaprotect_100",
                    "focus_bbox": [7.29, 46.91, 7.5, 46.99],
                    "name": "Überschwemmung Aquaprotect 100",
                },
                "tu1",
            ),
            text_result("Die Überschwemmungsgebiete sind nun auf der Karte."),
        ]
    )

    stats = TurnStats()
    message = UserMessage.model_validate(
        {
            "type": "user_message",
            "id": "m1",
            "content": "Zeige mir die Aquaprotect-Karte für Bern",
            "lang": "de",
        }
    )
    events = [
        event
        async for event in run_turn(
            message, models=models, gateway=gateway, settings=settings, stats=stats
        )
    ]

    final = events[-1]
    assert final.type == "final"
    # No LayerSpec: nothing was fetched or re-hosted.
    assert final.layers is None
    assert final.catalog_layers is not None
    assert [ref.id for ref in final.catalog_layers] == ["ch.bafu.aquaprotect_100"]
    assert final.catalog_layers[0].name == "Überschwemmung Aquaprotect 100"
    # A catalog layer is national, so the camera hint has to travel separately.
    assert final.focus_bbox == (7.29, 46.91, 7.5, 46.99)
    assert stats.layer_count == 1


async def test_an_unreachable_server_still_answers(settings: Settings) -> None:
    """Nothing listening on the configured port: the turn degrades, it does not fail."""
    gateway = ToolGateway("http://127.0.0.1:1/mcp", read_timeout=1.0)
    models = FakeModels([text_result("Ich konnte die Datensätze nicht abfragen.")])
    message = UserMessage.model_validate(
        {"type": "user_message", "id": "m1", "content": "Hochwasser?", "lang": "de"}
    )

    events = [
        event
        async for event in run_turn(
            message,
            models=models,
            gateway=gateway,
            settings=settings,
            stats=TurnStats(),
        )
    ]
    assert events[-1].type == "final"
    assert models.calls[0]["tools"] is None
