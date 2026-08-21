"""End-to-end smoke test for a running Streamable HTTP MCP endpoint."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from mcp import Client


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Smoke-test the Swisstopo Search MCP.")
    parser.add_argument("url", nargs="?", default="http://127.0.0.1:8791/mcp")
    return parser


async def smoke(url: str) -> dict[str, Any]:
    async with Client(url, read_timeout_seconds=60) as client:
        tools = await client.list_tools()
        resources = await client.list_resources()
        prompts = await client.list_prompts()
        datasets = await client.call_tool(
            "search_datasets",
            {"query": "avalanche hazards", "language": "en", "limit": 5},
        )
        divisions = await client.call_tool(
            "search_divisions",
            {"query": "Wallis", "kinds": ["kanton"], "limit": 3},
        )
        geocoded = await client.call_tool(
            "geocode_location",
            {
                "query": "Seftigenstrasse 264, 3084 Wabern",
                "origins": ["address"],
                "language": "en",
                "limit": 1,
            },
        )
        described = await client.call_tool(
            "describe_dataset",
            {
                "dataset_id": "ch.swisstopo-vd.stand-oerebkataster",
                "language": "en",
            },
        )

        dataset_content = datasets.structured_content
        division_content = divisions.structured_content
        geocode_content = geocoded.structured_content
        description_content = described.structured_content
        assert isinstance(dataset_content, dict) and dataset_content.get("datasets")
        assert isinstance(division_content, dict) and division_content.get("divisions")
        assert isinstance(geocode_content, dict) and geocode_content.get("locations")
        assert isinstance(description_content, dict) and description_content.get("dataset")

        focused_preview = await client.call_tool(
            "create_map_preview",
            {
                "dataset_ids": [dataset_content["datasets"][0]["dataset_id"]],
                "focus_bbox": division_content["divisions"][0]["bbox"],
                "language": "en",
            },
        )
        focused_preview_content = focused_preview.structured_content
        assert isinstance(focused_preview_content, dict)

        point = geocode_content["locations"][0]["coordinates"]["wgs84"]
        identified = await client.call_tool(
            "identify_at_point",
            {
                "preset": "all_relevant",
                "longitude": point["longitude"],
                "latitude": point["latitude"],
                "language": "en",
                "limit": 20,
            },
        )
        identify_content = identified.structured_content
        assert isinstance(identify_content, dict) and "feature_count" in identify_content
        explicit_identified = await client.call_tool(
            "identify_at_point",
            {
                "dataset_ids": ["ch.swisstopo-vd.amtliche-vermessung"],
                "longitude": point["longitude"],
                "latitude": point["latitude"],
                "language": "en",
            },
        )
        explicit_identify_content = explicit_identified.structured_content
        assert isinstance(explicit_identify_content, dict)
        assert dataset_content["datasets"][0]["map_preview_url"].startswith(
            "https://map.geo.admin.ch/#/map?"
        )
        assert geocode_content["locations"][0]["map_preview_url"].startswith(
            "https://map.geo.admin.ch/#/map?"
        )
        assert identify_content["selection"]["preset"] == "all_relevant"
        assert identify_content["geometry_omitted"] is True
        assert "layers=" in identify_content["map_preview_url"]
        assert explicit_identify_content["selection"]["preset"] is None
        assert explicit_identify_content["dataset_ids"] == ["ch.swisstopo-vd.amtliche-vermessung"]
        assert focused_preview_content["map_preview_scope"] == "division_bbox"
        focused_url = focused_preview_content["dataset_previews"][0]["map_preview_url"]
        assert "center=" in focused_url
        assert "z=1&" not in focused_url

    return {
        "endpoint": url,
        "tools": sorted(tool.name for tool in tools.tools),
        "resources": [str(resource.uri) for resource in resources.resources],
        "prompts": [prompt.name for prompt in prompts.prompts],
        "top_dataset": dataset_content["datasets"][0]["dataset_id"],
        "live_catalog": dataset_content["live_catalog"],
        "division": {
            key: division_content["divisions"][0][key]
            for key in ("name", "kind", "canton", "division_ref")
        },
        "geocode": geocode_content["locations"][0]["coordinates"],
        "described_dataset": description_content["dataset"]["dataset_id"],
        "field_count": len(description_content["dataset"].get("fields") or []),
        "identify_dataset_ids": identify_content["dataset_ids"],
        "identified_feature_count": identify_content["feature_count"],
        "explicit_identified_feature_count": explicit_identify_content["feature_count"],
        "map_preview_url": identify_content["map_preview_url"],
        "focused_map_preview_url": focused_preview_content["dataset_previews"][0][
            "map_preview_url"
        ],
        "oereb_official_links": [
            link["url"]
            for feature in identify_content["features"]
            for link in feature.get("external_links", [])
            if link.get("field") in {"oereb_extract_pdf", "oereb_extract_url"}
        ],
    }


if __name__ == "__main__":
    arguments = _parser().parse_args()
    print(json.dumps(asyncio.run(smoke(arguments.url)), indent=2, ensure_ascii=False))
