from __future__ import annotations

from typing import Any

import pytest
from mcp import Client

from swisstopo_mcp.catalog import CatalogIndex
from swisstopo_mcp.server import build_server

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


class StubGeoAdmin:
    async def search_datasets(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    async def describe_dataset(self, dataset_id: str, *, language: str) -> dict[str, Any] | None:
        if dataset_id == "ch.unknown.layer":
            return None
        return {
            "dataset_id": dataset_id,
            "title": "Test dataset",
            "language": language,
            "fields": [],
            "source": "live_geo_admin",
        }

    async def geocode_location(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [
            {
                "location_ref": "address:1",
                "kind": "address",
                "label": "Bundesplatz 3, Bern",
                "coordinates": {
                    "wgs84": {"longitude": 7.444, "latitude": 46.947, "crs": "EPSG:4326"},
                    "lv95": {"easting": 2600000.0, "northing": 1200000.0, "crs": "EPSG:2056"},
                },
                "match_quality": "exact",
                "related_features": [],
            }
        ]

    async def identify_at_point(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        return [
            {
                "feature_ref": {"dataset_id": "ch.test.layer", "feature_id": "42"},
                "dataset_title": "Test",
                "properties": {"name": "Example"},
                "external_links": [],
            }
        ]


async def test_mcp_catalog_exposes_selected_tools_resources_and_prompt() -> None:
    server = build_server(CatalogIndex(), StubGeoAdmin())
    async with Client(server) as client:
        tools = await client.list_tools()
        resources = await client.list_resources()
        templates = await client.list_resource_templates()
        prompts = await client.list_prompts()

    assert {tool.name for tool in tools.tools} == {
        "search_datasets",
        "describe_dataset",
        "search_divisions",
        "create_map_preview",
        "geocode_location",
        "identify_at_point",
        "explain_swisstopo",
    }
    identify_schema = next(tool for tool in tools.tools if tool.name == "identify_at_point")
    assert set(identify_schema.input_schema["required"]) == {"longitude", "latitude"}
    assert {"dataset_ids", "preset"} <= set(identify_schema.input_schema["properties"])
    assert all(tool.annotations and tool.annotations.read_only_hint for tool in tools.tools)
    assert {str(resource.uri) for resource in resources.resources} == {"swisstopo://catalog/stats"}
    assert {template.name for template in templates.resource_templates} == {"swisstopo-guide"}
    assert {prompt.name for prompt in prompts.prompts} == {"find_swiss_geodata"}


async def test_division_and_explanation_tools_return_structured_content() -> None:
    server = build_server(CatalogIndex(), StubGeoAdmin())
    async with Client(server) as client:
        division = await client.call_tool(
            "search_divisions",
            {"query": "Wallis", "kinds": ["kanton"], "limit": 2},
        )
        explanation = await client.call_tool("explain_swisstopo", {"topic": "coordinates"})

    assert division.structured_content["divisions"][0]["name"] == "Valais"
    assert division.structured_content["divisions"][0]["kind"] == "kanton"
    assert "EPSG:4326" in explanation.structured_content["content"]


async def test_dataset_search_and_description_are_client_neutral() -> None:
    server = build_server(CatalogIndex(), StubGeoAdmin())
    async with Client(server) as client:
        search = await client.call_tool(
            "search_datasets",
            {"query": "avalanche hazards", "language": "en", "limit": 3},
        )
        dataset_id = search.structured_content["datasets"][0]["dataset_id"]
        description = await client.call_tool(
            "describe_dataset", {"dataset_id": dataset_id, "language": "en"}
        )

    assert dataset_id.startswith("ch.")
    assert "layer" not in search.structured_content
    assert search.structured_content["datasets"][0]["map_preview_url"].startswith(
        "https://map.geo.admin.ch/#/map?"
    )
    assert description.structured_content["dataset"]["source"] == "live_geo_admin"
    assert "layers=" in description.structured_content["dataset"]["map_preview_url"]
    assert search.structured_content["datasets"][0]["map_preview_scope"] == "switzerland"
    assert "create_map_preview" in search.structured_content["map_link_note"]


async def test_create_map_preview_returns_one_centred_link_per_dataset() -> None:
    server = build_server(CatalogIndex(), StubGeoAdmin())
    async with Client(server) as client:
        preview = await client.call_tool(
            "create_map_preview",
            {
                "dataset_ids": [
                    "ch.bfs.gebaeude_wohnungs_register",
                    "ch.swisstopo.vec25-gebaeude",
                ],
                "focus_bbox": [7.874858, 47.311028, 7.929085, 47.368924],
                "language": "en",
            },
        )

    content = preview.structured_content
    assert content["map_preview_scope"] == "division_bbox"
    assert content["focus"]["crs"] == "EPSG:4326"
    assert [item["dataset_id"] for item in content["dataset_previews"]] == [
        "ch.bfs.gebaeude_wohnungs_register",
        "ch.swisstopo.vec25-gebaeude",
    ]
    for item in content["dataset_previews"]:
        url = item["map_preview_url"]
        assert "center=2635016.954,1243338.400" in url
        assert "z=1" not in url
        assert f"layers={item['dataset_id']}" in url
        assert ";" not in url
    assert (
        "layers=ch.bfs.gebaeude_wohnungs_register;ch.swisstopo.vec25-gebaeude"
        in content["combined_map_preview_url"]
    )
    assert "individual links" in content["presentation_note"]


async def test_geocode_and_identify_work_without_session_state() -> None:
    server = build_server(CatalogIndex(), StubGeoAdmin())
    async with Client(server) as client:
        geocoded = await client.call_tool(
            "geocode_location",
            {"query": "Bundesplatz 3 Bern", "origins": ["address"], "limit": 1},
        )
        point = geocoded.structured_content["locations"][0]["coordinates"]["wgs84"]
        identified = await client.call_tool(
            "identify_at_point",
            {
                "dataset_ids": ["ch.test.layer"],
                "longitude": point["longitude"],
                "latitude": point["latitude"],
            },
        )

    assert identified.structured_content["feature_count"] == 1
    assert identified.structured_content["features"][0]["properties"]["name"] == "Example"
    assert geocoded.structured_content["locations"][0]["map_preview_url"].startswith(
        "https://map.geo.admin.ch/#/map?"
    )
    assert identified.structured_content["geometry_omitted"] is True
    assert "verbatim" in identified.structured_content["map_link_note"]
    assert "ch.test.layer" in identified.structured_content["map_preview_url"]
    assert "@features=42" in identified.structured_content["features"][0]["map_feature_url"]


async def test_identify_preset_can_be_combined_with_explicit_dataset_ids() -> None:
    server = build_server(CatalogIndex(), StubGeoAdmin())
    async with Client(server) as client:
        identified = await client.call_tool(
            "identify_at_point",
            {
                "longitude": 7.451352,
                "latitude": 46.927937,
                "preset": "all_relevant",
                "dataset_ids": ["ch.test.layer"],
            },
        )

    assert identified.structured_content["dataset_ids"] == [
        "ch.swisstopo-vd.amtliche-vermessung",
        "ch.swisstopo-vd.stand-oerebkataster",
        "ch.test.layer",
    ]
    assert identified.structured_content["selection"]["preset"] == "all_relevant"
    assert "oereb_note" in identified.structured_content


async def test_validation_errors_are_structured_and_non_retryable() -> None:
    server = build_server(CatalogIndex(), StubGeoAdmin())
    async with Client(server) as client:
        empty = await client.call_tool("search_datasets", {"query": ""})
        bad_origin = await client.call_tool(
            "geocode_location", {"query": "Bern", "origins": ["unsupported"]}
        )
        bad_coordinates = await client.call_tool(
            "identify_at_point",
            {"dataset_ids": ["ch.test.layer"], "longitude": 500, "latitude": 200},
        )
        bad_preset = await client.call_tool(
            "identify_at_point",
            {"preset": "buildings", "longitude": 7.4, "latitude": 46.9},
        )
        missing_selection = await client.call_tool(
            "identify_at_point",
            {"longitude": 7.4, "latitude": 46.9},
        )
        missing_map_focus = await client.call_tool(
            "create_map_preview",
            {"dataset_ids": ["ch.test.layer"]},
        )
        conflicting_map_focus = await client.call_tool(
            "create_map_preview",
            {
                "dataset_ids": ["ch.test.layer"],
                "focus_bbox": [7.3, 46.8, 7.5, 47.0],
                "longitude": 7.4,
                "latitude": 46.9,
            },
        )

    for result in (
        empty,
        bad_origin,
        bad_coordinates,
        bad_preset,
        missing_selection,
        missing_map_focus,
        conflicting_map_focus,
    ):
        assert result.structured_content["error"]["retryable"] is False


async def test_catalog_stats_resource_is_machine_readable() -> None:
    server = build_server(CatalogIndex(), StubGeoAdmin())
    async with Client(server) as client:
        resource = await client.read_resource("swisstopo://catalog/stats")
        guide = await client.read_resource("swisstopo://guide/divisions")

    assert resource.contents[0].mime_type == "application/json"
    assert '"datasets": 896' in resource.contents[0].text
    assert '"divisions": 6272' in resource.contents[0].text
    assert "locality" in guide.contents[0].text
    assert "bbox" in guide.contents[0].text
