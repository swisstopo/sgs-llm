"""Displayable catalogue layers need not have a vector feature table."""

import asyncio

import httpx
import pytest
from mcp import Client

from .server import build_server
from .swisstopo import Swisstopo
from .test_server import RecordingArtifacts, StubBoundaries, StubIndex


@pytest.mark.parametrize(
    "layer_id",
    [
        "ch.agroscope.abschaetzung-organische_boeden",
        "ch.agroscope.amphibien-ausbreitungskarten_bombia_variegata",
    ],
)
@pytest.mark.parametrize("tooltip", [False, True])
def test_display_only_layer_can_be_described_and_offered(layer_id, tooltip):
    # The specific 400 body returned by these official schema endpoints.
    def respond(request):
        return httpx.Response(
            400, text=f"400 Bad Request\nNo Vector Table was found for {layer_id}\n"
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            api = Swisstopo(client)
            api._layers_config = {
                "en": {
                    layer_id: {
                        "label": "Official map",
                        "type": "wmts",
                        "tooltip": tooltip,
                    }
                }
            }
            api._metadata = {
                "en": {
                    layer_id: {
                        "abstract": "Dataset description",
                        "dataOwner": "Agroscope",
                        "urlDetails": "https://example.test/details",
                        "downloadUrl": "https://example.test/download",
                    }
                }
            }
            server = build_server(StubIndex(), api, RecordingArtifacts(), StubBoundaries())
            async with Client(server) as mcp:
                described = await mcp.call_tool(
                    "describe_layer", {"layer_id": layer_id, "lang": "en"}
                )
                assert not described.is_error
                layer = described.structured_content["layer"]
                assert layer["description"] == "Dataset description"
                assert layer["owner"] == "Agroscope"
                assert layer["details_url"] == "https://example.test/details"
                assert layer["download_url"] == "https://example.test/download"
                assert layer["legend_url"]
                assert layer["displayable"] is True
                assert layer["queryable"] is False
                assert layer["fields"] == []
                assert layer["geometry_type"] is None
                assert "display_catalog_layer" in layer["query_note"]
                offered = await mcp.call_tool(
                    "display_catalog_layer", {"layer_id": layer_id, "lang": "en"}
                )
                assert offered.structured_content["catalog_layer"]["id"] == layer_id

    asyncio.run(run())


def test_vector_description_preserves_bounded_field_examples():
    def respond(request):
        return httpx.Response(
            200,
            json={
                "fields": [
                    {
                        "name": "species_corridors",
                        "type": "VARCHAR",
                        "values": [
                            "",
                            "Bombina variegata, Bufo bufo",
                            "Hyla arborea",
                            "Triturus cristatus",
                            "Rana temporaria",
                            "example beyond the limit",
                        ],
                    },
                    {
                        "name": "bedeutung_parzelle",
                        "type": "VARCHAR",
                        "values": [
                            "Pot. Nutzung als Korridor durch mind. 1 untersuchte Amphibienart"
                        ],
                    },
                    {"name": "id", "type": "INTEGER", "values": [1, 2]},
                    {
                        "name": "unbounded",
                        "values": ["x" * 501, {"nested": "value"}, "usable"],
                    },
                ]
            },
        )

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            api = Swisstopo(client)
            api._layers_config = {"en": {"ch.test": {"type": "wmts", "tooltip": True}}}
            api._metadata = {"en": {}}
            layer = await api.describe_layer("ch.test", "en")
            assert layer["queryable"] is True
            fields = {field["name"]: field for field in layer["fields"]}
            assert fields["species_corridors"]["sample_values"] == [
                "",
                "Bombina variegata, Bufo bufo",
                "Hyla arborea",
                "Triturus cristatus",
                "Rana temporaria",
            ]
            assert fields["id"]["sample_values"] == [1, 2]
            assert fields["unbounded"]["sample_values"] == ["usable"]
            assert fields["bedeutung_parzelle"]["sample_values"]
            assert "query_note" not in layer

    asyncio.run(run())


@pytest.mark.parametrize("status,body", [(400, "Invalid request parameter"), (503, "Unavailable")])
def test_unrelated_schema_failure_is_not_a_capability_verdict(status, body):
    async def run():
        transport = httpx.MockTransport(lambda request: httpx.Response(status, text=body))
        async with httpx.AsyncClient(transport=transport) as client:
            api = Swisstopo(client)
            api._layers_config = {"de": {"ch.test": {"tooltip": True}}}
            api._metadata = {"de": {}}
            with pytest.raises(httpx.HTTPStatusError):
                await api.describe_layer("ch.test")

    asyncio.run(run())


def test_unknown_layer_does_not_request_a_schema():
    def unexpected(request):
        pytest.fail("An unknown catalogue ID must not request a schema")

    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(unexpected)) as client:
            api = Swisstopo(client)
            api._layers_config = {"de": {"known": {}}}
            assert await api.describe_layer("missing") is None

    asyncio.run(run())
