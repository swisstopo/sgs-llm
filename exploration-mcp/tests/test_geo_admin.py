from __future__ import annotations

import asyncio
import math
from typing import Any

import httpx
import pytest

from swisstopo_mcp.geo_admin import (
    GeoAdminClient,
    GeoAdminError,
    _latest_timestamp,
    _published_year,
    _timestamp_for_year,
)


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


def test_layers_config_is_refetched_on_every_call() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        assert request.url.path.endswith("/layersConfig")
        calls += 1
        year = 2025 + calls
        return _response(
            request,
            {"ch.test.layer": {"timeEnabled": True, "timestamps": [str(year)]}},
        )

    async def run() -> tuple[dict[str, Any], dict[str, Any]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            api = GeoAdminClient(http)
            first = await api.layers_config("en")
            second = await api.layers_config("en")
            return first, second

    first, second = asyncio.run(run())
    assert calls == 2
    assert first["ch.test.layer"]["timestamps"] == ["2026"]
    assert second["ch.test.layer"]["timestamps"] == ["2027"]


def test_layer_metadata_is_refetched_on_every_call() -> None:
    calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        assert request.url.path.endswith("/api/MapServer")
        calls += 1
        return _response(
            request,
            {
                "layers": [
                    {
                        "layerBodId": "ch.test.layer",
                        "attributes": {"dataStatus": f"revision-{calls}"},
                    }
                ]
            },
        )

    async def run() -> tuple[dict[str, Any], dict[str, Any]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            api = GeoAdminClient(http)
            first = await api.layer_metadata("en")
            second = await api.layer_metadata("en")
            return first, second

    first, second = asyncio.run(run())
    assert calls == 2
    assert first["ch.test.layer"]["dataStatus"] == "revision-1"
    assert second["ch.test.layer"]["dataStatus"] == "revision-2"


def test_repeated_identify_uses_newly_published_latest_year_without_restart() -> None:
    config_calls = 0
    identify_years: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal config_calls
        if request.url.path.endswith("/layersConfig"):
            config_calls += 1
            latest_year = 2025 + config_calls
            return _response(
                request,
                {
                    "ch.test.history": {
                        "timeEnabled": True,
                        "timestamps": [str(latest_year), "2025"],
                    }
                },
            )
        selected_year = request.url.params["timeInstant"]
        identify_years.append(selected_year)
        return _response(
            request,
            {
                "results": [
                    {
                        "layerBodId": "ch.test.history",
                        "layerName": "Historic layer",
                        "featureId": f"feature-{selected_year}",
                        "properties": {"jahr": int(selected_year)},
                    }
                ]
            },
        )

    async def run() -> tuple[dict[str, Any], dict[str, Any]]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            api = GeoAdminClient(http)
            first = await api.identify_at_point(
                ["ch.test.history"], 7.0, 46.0, language="en", limit=20
            )
            second = await api.identify_at_point(
                ["ch.test.history"], 7.0, 46.0, language="en", limit=20
            )
            return first, second

    first, second = asyncio.run(run())
    assert config_calls == 2
    assert identify_years == ["2026", "2027"]
    assert first["temporal_context"]["datasets"][0]["year_used"] == 2026
    assert second["temporal_context"]["datasets"][0]["year_used"] == 2027


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
    assert result["latest_year"] == 2026
    assert result["available_years"] == [2025, 2026]
    assert result["fields"] == [{"name": "status", "alias": "Status", "type": "VARCHAR"}]


@pytest.mark.parametrize(
    ("timestamps", "expected"),
    [
        ([], None),
        (["2015", "2026", "1850"], "2026"),
        (["2023-08-31T23:59:59Z", "2025-08-31T23:59:59Z"], "2025-08-31T23:59:59Z"),
        (["19991231", "20251231", "20231231"], "20251231"),
        (["2025", "current", "2024"], "current"),
        (["20250101", "99990101", "20240101"], "99990101"),
    ],
)
def test_latest_timestamp_supports_every_geoadmin_timestamp_format(
    timestamps: list[str], expected: str | None
) -> None:
    assert _latest_timestamp(timestamps) == expected


@pytest.mark.parametrize(
    ("timestamp", "expected"),
    [
        ("2026", 2026),
        ("2015-08-31T23:59:59Z", 2015),
        ("20251231", 2025),
        ("current", None),
        ("99991231", None),
        ("not-a-time", None),
    ],
)
def test_published_year_normalizes_timestamp_formats(
    timestamp: str, expected: int | None
) -> None:
    assert _published_year(timestamp) == expected


@pytest.mark.parametrize(
    ("timestamps", "year", "expected"),
    [
        (["2026", "2015"], 2015, "2015"),
        (["2025-08-31T23:59:59Z", "2015-08-31T23:59:59Z"], 2015, "2015-08-31T23:59:59Z"),
        (["20251231", "20151231"], 2015, "20151231"),
        (["current", "2025"], 2026, None),
        (["2026", "2024"], 2015, None),
    ],
)
def test_explicit_year_resolves_only_published_years(
    timestamps: list[str], year: int, expected: str | None
) -> None:
    assert _timestamp_for_year(timestamps, year) == expected


def test_identify_keeps_properties_and_external_links_without_geometry() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/layersConfig"):
            return _response(request, {"ch.test.layer": {"timeEnabled": False}})
        assert request.url.params["returnGeometry"] == "false"
        assert "timeInstant" not in request.url.params
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

    async def run() -> dict[str, Any]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await GeoAdminClient(http).identify_at_point(
                ["ch.test.layer"], 7.0, 46.0, language="en", limit=20
            )

    result = asyncio.run(run())
    features = result["features"]
    assert features[0]["feature_ref"] == {
        "dataset_id": "ch.test.layer",
        "feature_id": "42",
    }
    assert "geometry" not in features[0]
    assert features[0]["external_links"][0]["kind"] == "pdf"
    assert result["temporal_context"]["datasets"] == [
        {
            "dataset_id": "ch.test.layer",
            "time_enabled": False,
            "timestamp_used": None,
            "year_used": None,
            "selection": "not_applicable",
        }
    ]


def test_identify_defaults_historicised_layer_to_latest_published_year() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/layersConfig"):
            return _response(
                request,
                {
                    "ch.swisstopo.swissboundaries3d-gemeinde-flaeche.fill": {
                        "timeEnabled": True,
                        # Deliberately unsorted: selection must not depend on API order.
                        "timestamps": ["2015", "2026", "1850", "2016"],
                    }
                },
            )
        assert request.url.params["timeInstant"] == "2026"
        return _response(
            request,
            {
                "results": [
                    {
                        "layerBodId": (
                            "ch.swisstopo.swissboundaries3d-gemeinde-flaeche.fill"
                        ),
                        "layerName": "Municipal boundaries",
                        "featureId": "5401-2026",
                        "properties": {
                            "gemeindename": "Aigle",
                            "gemflaeche": 1641.0,
                            "jahr": 2026,
                        },
                    }
                ]
            },
        )

    async def run() -> dict[str, Any]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await GeoAdminClient(http).identify_at_point(
                ["ch.swisstopo.swissboundaries3d-gemeinde-flaeche.fill"],
                6.96974,
                46.31642,
                language="en",
                limit=20,
            )

    result = asyncio.run(run())
    assert result["features"][0]["properties"]["gemflaeche"] == 1641.0
    assert result["temporal_context"]["mode"] == "latest_by_dataset"
    assert result["temporal_context"]["datasets"][0]["timestamp_used"] == "2026"
    assert result["temporal_context"]["datasets"][0]["year_used"] == 2026


def test_identify_resolves_explicit_historical_year() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/layersConfig"):
            return _response(
                request,
                {
                    "ch.test.history": {
                        "timeEnabled": True,
                        "timestamps": ["2025-08-31T23:59:59Z", "2015-08-31T23:59:59Z"],
                    }
                },
            )
        assert request.url.params["timeInstant"] == "2015-08-31T23:59:59Z"
        return _response(
            request,
            {
                "results": [
                    {
                        "layerBodId": "ch.test.history",
                        "layerName": "Historic layer",
                        "featureId": "a-2015",
                        "properties": {"area": 1635.738, "jahr": 2015},
                    }
                ]
            },
        )

    async def run() -> dict[str, Any]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await GeoAdminClient(http).identify_at_point(
                ["ch.test.history"],
                6.96974,
                46.31642,
                language="en",
                limit=20,
                year=2015,
            )

    result = asyncio.run(run())
    assert result["features"][0]["properties"]["area"] == 1635.738
    assert result["temporal_context"]["requested_year"] == 2015
    assert result["temporal_context"]["mode"] == "explicit_year"
    assert result["temporal_context"]["datasets"][0]["selection"] == "explicit_year"


def test_identify_rejects_unavailable_historical_year_before_querying() -> None:
    identify_called = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal identify_called
        if request.url.path.endswith("/layersConfig"):
            return _response(
                request,
                {"ch.test.history": {"timeEnabled": True, "timestamps": ["2024", "2026"]}},
            )
        identify_called = True
        raise AssertionError("identify must not run for an unavailable year")

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(GeoAdminError, match="Year 2015 is not available") as exc_info:
                await GeoAdminClient(http).identify_at_point(
                    ["ch.test.history"],
                    7.0,
                    46.0,
                    language="en",
                    limit=20,
                    year=2015,
                )
            assert exc_info.value.code == "time_not_available"
            assert exc_info.value.retryable is False
            assert exc_info.value.details == {
                "dataset_id": "ch.test.history",
                "requested_year": 2015,
                "available_years": [2024, 2026],
                "latest_timestamp": "2026",
                "latest_year": 2026,
            }

    asyncio.run(run())
    assert identify_called is False


def test_identify_rejects_time_enabled_layer_without_timestamp_metadata() -> None:
    identify_called = False

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal identify_called
        if request.url.path.endswith("/layersConfig"):
            return _response(
                request,
                {"ch.test.broken-time": {"timeEnabled": True, "timestamps": []}},
            )
        identify_called = True
        raise AssertionError("identify must not run without temporal metadata")

    async def run() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            with pytest.raises(GeoAdminError) as exc_info:
                await GeoAdminClient(http).identify_at_point(
                    ["ch.test.broken-time"],
                    7.0,
                    46.0,
                    language="en",
                    limit=20,
                )
            assert exc_info.value.code == "temporal_metadata_unavailable"
            assert exc_info.value.retryable is False

    asyncio.run(run())
    assert identify_called is False


def test_identify_groups_layers_that_share_the_same_latest_timestamp() -> None:
    identify_requests: list[tuple[str, str | None]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/layersConfig"):
            return _response(
                request,
                {
                    "ch.test.first": {"timeEnabled": True, "timestamps": ["2026"]},
                    "ch.test.second": {"timeEnabled": True, "timestamps": ["2026", "2025"]},
                    "ch.test.static": {"timeEnabled": False},
                },
            )
        layers = request.url.params["layers"].removeprefix("all:")
        identify_requests.append((layers, request.url.params.get("timeInstant")))
        return _response(request, {"results": []})

    async def run() -> dict[str, Any]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await GeoAdminClient(http).identify_at_point(
                ["ch.test.first", "ch.test.second", "ch.test.static"],
                7.0,
                46.0,
                language="en",
                limit=20,
            )

    result = asyncio.run(run())
    assert identify_requests == [
        ("ch.test.first,ch.test.second", "2026"),
        ("ch.test.static", None),
    ]
    assert result["features"] == []
    assert [
        dataset["selection"] for dataset in result["temporal_context"]["datasets"]
    ] == ["latest_published", "latest_published", "not_applicable"]


def test_identify_applies_limit_after_merging_temporal_groups() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/layersConfig"):
            return _response(
                request,
                {
                    "ch.test.first": {"timeEnabled": True, "timestamps": ["2026"]},
                    "ch.test.second": {"timeEnabled": True, "timestamps": ["2025"]},
                },
            )
        dataset_id = request.url.params["layers"].removeprefix("all:")
        return _response(
            request,
            {
                "results": [
                    {
                        "layerBodId": dataset_id,
                        "layerName": dataset_id,
                        "featureId": dataset_id,
                        "properties": {},
                    }
                ]
            },
        )

    async def run() -> dict[str, Any]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await GeoAdminClient(http).identify_at_point(
                ["ch.test.first", "ch.test.second"],
                7.0,
                46.0,
                language="en",
                limit=1,
            )

    result = asyncio.run(run())
    assert len(result["features"]) == 1
    assert result["features"][0]["feature_ref"]["dataset_id"] == "ch.test.first"


def test_identify_groups_layers_by_effective_timestamp_and_preserves_dataset_order() -> None:
    identify_requests: list[tuple[str, str | None]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/layersConfig"):
            return _response(
                request,
                {
                    "ch.test.static": {"timeEnabled": False},
                    "ch.test.newer": {"timeEnabled": True, "timestamps": ["2026", "2025"]},
                    "ch.test.older": {"timeEnabled": True, "timestamps": ["2024", "2023"]},
                },
            )
        layers = request.url.params["layers"].removeprefix("all:")
        timestamp = request.url.params.get("timeInstant")
        identify_requests.append((layers, timestamp))
        return _response(
            request,
            {
                "results": [
                    {
                        "layerBodId": layers,
                        "layerName": layers,
                        "featureId": layers.rsplit(".", 1)[-1],
                        "properties": {},
                    }
                ]
            },
        )

    requested_ids = ["ch.test.older", "ch.test.static", "ch.test.newer"]

    async def run() -> dict[str, Any]:
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            return await GeoAdminClient(http).identify_at_point(
                requested_ids, 7.0, 46.0, language="en", limit=20
            )

    result = asyncio.run(run())
    assert identify_requests == [
        ("ch.test.older", "2024"),
        ("ch.test.static", None),
        ("ch.test.newer", "2026"),
    ]
    assert [feature["feature_ref"]["dataset_id"] for feature in result["features"]] == requested_ids
    assert [
        item["year_used"] for item in result["temporal_context"]["datasets"]
    ] == [2024, None, 2026]
