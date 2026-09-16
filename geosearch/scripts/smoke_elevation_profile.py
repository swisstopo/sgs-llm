"""Read-only live profile checks: python -m geosearch.scripts.smoke_elevation_profile.

Requires geosearch dependencies, no AWS credentials or writes. The first route is
geo.admin.ch's documented example. The second selects the longest fetched LineString
in a small Schwarzsee area as an explicitly labelled segment, not a whole itinerary.
"""

from __future__ import annotations

import asyncio
import json
import math
from typing import Any

import httpx
from pyproj import Transformer

from geosearch.elevation import project_route
from geosearch.swisstopo import Swisstopo


def summary(profile: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in profile.items() if key != "samples"}


async def main() -> None:
    async with httpx.AsyncClient(timeout=60) as client:
        api = Swisstopo(client)
        wgs84 = Transformer.from_crs(2056, 4326, always_xy=True)
        example = {
            "type": "LineString",
            "coordinates": [
                list(wgs84.transform(x, y))
                for x, y in [(2550050, 1206550), (2556950, 1204150), (2561050, 1207950)]
            ],
        }
        example_result = await api.elevation_profile(example, samples=20)
        layer = "ch.swisstopo.swisstlm3d-wanderwege"
        bbox = [7.28, 46.67, 7.30, 46.68]
        fetched = await api.fetch_features(layer, bbox, grid=1)
        lines = [f for f in fetched if f["geometry"]["type"] == "LineString"]

        def length(feature: dict[str, Any]) -> float:
            points = project_route(feature["geometry"])["coordinates"]
            return sum(math.dist(a, b) for a, b in zip(points, points[1:]))

        selected = max(lines, key=length)
        segment_result = await api.elevation_profile(selected["geometry"], samples=100)
        print(
            json.dumps(
                {
                    "official_example": summary(example_result),
                    "schwarzsee_segment": {
                        "layer_id": layer,
                        "bbox": bbox,
                        "feature_id": selected["id"],
                        "selection": "longest fetched LineString segment",
                        **summary(segment_result),
                    },
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    asyncio.run(main())
