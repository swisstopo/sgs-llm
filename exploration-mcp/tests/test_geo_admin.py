from __future__ import annotations

import asyncio
import math
from typing import Any

import httpx

from swisstopo_mcp.geo_admin import GeoAdminClient


def _response(request: httpx.Request, payload: dict[str, Any], status: int = 200) -> httpx.Response:
    return httpx.Response(status, json=payload, request=request)


def test_geocoder_uses_explicit_lon_lat_and_derives_lv95() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["sr"] == "4326"
        return _response(
            request,
            {
                "features": [
                    {
                        "properties": {
                            "featureId": "1272199_0",
                            "origin": "address",
                            "label": "Seftigenstrasse 264 <b>3084 Wabern</b>",
                            "detail": "seftigenstrasse 264 3084 wabern 355 koeniz ch be",
                            # Deliberately nonsense: these ambiguous fields must be ignored.
                            "x": 999,
                            "y": 888,
                            "lon": 7.451352119445801,
                            "lat": 46.92793655395508,
                            "links": [
                                {
                                    "title": "ch.swisstopo.amtliches-gebaeudeadressverzeichnis",
                                    "href": "/rest/services/ech/MapServer/ch.test/100718281",
                                }
                            ],
                        }
                    }
                ]
            },
        )

    async def run() -> list[dict[str, Any]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            api = GeoAdminClient(http)
            return await api.geocode_location(
                "Seftigenstrasse 264, 3084 Wabern",
                origins=["address"],
                language="en",
                limit=1,
            )

    locations = asyncio.run(run())
    coordinates = locations[0]["coordinates"]
    assert coordinates["wgs84"]["longitude"] == 7.451352119445801
    assert coordinates["wgs84"]["latitude"] == 46.92793655395508
    assert math.isclose(coordinates["lv95"]["easting"], 2600968.7, abs_tol=0.2)
    assert math.isclose(coordinates["lv95"]["northing"], 1197427.0, abs_tol=0.2)
    assert locations[0]["label"] == "Seftigenstrasse 264 3084 Wabern"
    assert locations[0]["match_quality"] == "exact"


def test_canton_alias_is_looked_up_by_code() -> None:
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.url.params["searchText"] == "VS"
        assert request.url.params["origins"] == "kantone"
        return _response(
            request,
            {
                "results": [
                    {
                        "attrs": {
                            "featureId": "1",
                            "origin": "kantone",
                            "label": "Valais",
                            "detail": "Valais Wallis",
                            "lon": 7.6,
                            "lat": 46.2,
                        }
                    }
                ]
            },
        )

    async def run() -> list[dict[str, Any]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await GeoAdminClient(http).geocode_location(
                "Wallis", origins=["kantone"], language="de", limit=3
            )

    locations = asyncio.run(run())
    assert len(requests) == 1
    assert locations[0]["label"] == "Valais"


def test_describe_dataset_merges_config_metadata_and_schema() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/layersConfig"):
            return _response(
                request,
                {
                    "ch.test.layer": {
                        "label": "Test layer",
                        "type": "wms",
                        "tooltip": True,
                        "timeEnabled": True,
                        "timestamps": ["2025", "2026"],
                    }
                },
            )
        if path.endswith("/api/MapServer"):
            return _response(
                request,
                {
                    "layers": [
                        {
                            "layerBodId": "ch.test.layer",
                            "attributes": {
                                "abstract": "Official description",
                                "dataOwner": "Test office",
                                "urlDetails": "https://example.test/details",
                            },
                        }
                    ]
                },
            )
        if path.endswith("/ech/MapServer/ch.test.layer"):
            return _response(
                request,
                {
                    "geometryType": "esriGeometryPolygon",
                    "fields": [{"name": "status", "alias": "Status", "type": "VARCHAR"}],
                },
            )
        raise AssertionError(path)

    async def run() -> dict[str, Any] | None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await GeoAdminClient(http).describe_dataset("ch.test.layer", language="en")

    result = asyncio.run(run())
    assert result is not None
    assert result["owner"] == "Test office"
    assert result["queryable"] is True
    assert result["current_timestamp"] == "2026"
    assert result["fields"] == [{"name": "status", "alias": "Status", "type": "VARCHAR"}]


def test_identify_keeps_properties_and_external_links_without_geometry() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["returnGeometry"] == "false"
        return _response(
            request,
            {
                "results": [
                    {
                        "layerBodId": "ch.test.layer",
                        "layerName": "Test layer",
                        "featureId": 42,
                        "geometry": {"type": "Point", "coordinates": [7.0, 46.0]},
                        "properties": {
                            "name": "Example",
                            "document": "https://example.test/document.pdf",
                        },
                    }
                ]
            },
        )

    async def run() -> list[dict[str, Any]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await GeoAdminClient(http).identify_at_point(
                ["ch.test.layer"], 7.0, 46.0, language="en", limit=20
            )

    features = asyncio.run(run())
    assert features[0]["feature_ref"] == {
        "dataset_id": "ch.test.layer",
        "feature_id": "42",
    }
    assert "geometry" not in features[0]
    assert features[0]["external_links"][0]["kind"] == "pdf"
