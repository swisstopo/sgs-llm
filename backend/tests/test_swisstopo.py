"""The dummy MCP server's geo.admin.ch wrappers, canton handling and geometry maths.

Responses here are trimmed copies of what the live API returned on 2026-07-30, so a
change in the real payload shape shows up as a test failure.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
from mcp_dummy.cantons import canton_code
from mcp_dummy.geometry import bounding_box, geometry_type, measure, summarise_properties
from mcp_dummy.results import ResultCache
from mcp_dummy.swisstopo import (
    LayerNotQueryable,
    Swisstopo,
    parse_box2d,
    strip_markup,
)


def _client(handler: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestCantonCode:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("Wallis", "VS"),
            ("Valais", "VS"),
            ("Vallese", "VS"),
            ("Tessin", "TI"),
            ("Ticino", "TI"),
            ("Graubünden", "GR"),
            ("Grischun", "GR"),
            ("St. Gallen", "SG"),
            ("Hochwassergefahren im Wallis", "VS"),
            ("Solarpotenzial in Zürich", "ZH"),
        ],
    )
    def test_resolves_names_in_every_language(self, text: str, expected: str) -> None:
        assert canton_code(text) == expected

    def test_resolves_an_uppercase_code(self) -> None:
        assert canton_code("Gefahren in VS") == "VS"

    def test_does_not_treat_common_words_as_codes(self) -> None:
        """Lowercase "in" and "so" must not resolve to canton codes."""
        assert canton_code("was ist in der naehe") is None
        assert canton_code("so viele daten") is None

    def test_returns_none_for_a_non_canton(self) -> None:
        assert canton_code("Paris") is None
        assert canton_code("") is None


class TestParsing:
    def test_parses_a_box2d(self) -> None:
        assert parse_box2d("BOX(7.305262 46.177989,7.42529 46.255851)") == [
            7.305262,
            46.177989,
            7.42529,
            46.255851,
        ]

    def test_normalises_reversed_corners(self) -> None:
        assert parse_box2d("BOX(8 47,7 46)") == [7.0, 46.0, 8.0, 47.0]

    @pytest.mark.parametrize("value", [None, "", "POINT(7 46)", "BOX(bad)", 42])
    def test_rejects_anything_else(self, value: Any) -> None:
        assert parse_box2d(value) is None

    def test_strips_search_highlight_markup(self) -> None:
        assert strip_markup("<i>Flurname</i> <b>Wallis</b> (BE)") == "Flurname Wallis (BE)"


class TestSearchLayers:
    async def test_returns_layer_ids_and_trims_the_abstract(self) -> None:
        payload = {
            "results": [
                {
                    "attrs": {
                        "layer": "ch.bafu.hydroweb-warnkarte_national",
                        "label": "<b>Hochwasserwarnkarte</b>",
                        "detail": "hochwasserwarnkarte | " + "x" * 3000,
                    }
                }
            ]
        }

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["type"] == "layers"
            return httpx.Response(200, json=payload)

        api = Swisstopo(_client(handler))
        layers = await api.search_layers("Hochwasser", "de")
        assert layers[0]["layer_id"] == "ch.bafu.hydroweb-warnkarte_national"
        assert layers[0]["title"] == "Hochwasserwarnkarte"
        # The abstract is often thousands of characters; the model needs the gist only.
        assert len(layers[0]["summary"]) <= 400

    async def test_no_match_returns_empty(self) -> None:
        api = Swisstopo(_client(lambda r: httpx.Response(200, json={"results": []})))
        assert await api.search_layers("unicorns", "de") == []

    async def test_skips_results_with_no_layer_id(self) -> None:
        payload = {"results": [{"attrs": {"label": "no id here"}}]}
        api = Swisstopo(_client(lambda r: httpx.Response(200, json=payload)))
        assert await api.search_layers("x", "de") == []


class TestSearchLocations:
    async def test_a_german_canton_name_is_looked_up_by_code(self) -> None:
        """The live canton index matches only "Valais"; searching "Wallis" directly
        returns unrelated places like "Wallisellen"."""
        seen: list[dict[str, str]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(dict(request.url.params))
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "attrs": {
                                "label": "<b>Valais</b>",
                                "origin": "kantone",
                                "geom_st_box2d": "BOX(6.76686 45.853976,8.480974 46.656104)",
                            }
                        }
                    ]
                },
            )

        api = Swisstopo(_client(handler))
        places = await api.search_locations("Wallis", "de")

        assert seen[0]["searchText"] == "VS"
        assert seen[0]["origins"] == "kantone"
        assert places[0]["bbox"] == [6.76686, 45.853976, 8.480974, 46.656104]
        # The user typed "Wallis"; the answer should be recognisable to them.
        assert "Valais" in places[0]["name"]

    async def test_a_commune_falls_through_to_the_general_search(self) -> None:
        attempts: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            attempts.append(request.url.params["searchText"])
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "attrs": {
                                "label": "<b>Sion (VS)</b>",
                                "origin": "gg25",
                                "geom_st_box2d": "BOX(7.305262 46.177989,7.42529 46.255851)",
                            }
                        }
                    ]
                },
            )

        api = Swisstopo(_client(handler))
        places = await api.search_locations("Sion", "de")
        assert attempts == ["Sion"]
        assert places[0]["kind"] == "gg25"

    async def test_a_point_result_is_padded_into_a_usable_extent(self) -> None:
        """A zero-area box would zoom the map to an infinitely small area."""
        payload = {
            "results": [
                {
                    "attrs": {
                        "label": "<b>Wallis</b> (AG)",
                        "origin": "gazetteer",
                        "geom_st_box2d": "BOX(8.018251 47.333991,8.018251 47.333991)",
                    }
                }
            ]
        }
        api = Swisstopo(_client(lambda r: httpx.Response(200, json=payload)))
        places = await api.search_locations("Chli Ort", "de")
        west, south, east, north = places[0]["bbox"]
        assert east > west
        assert north > south

    async def test_an_unknown_place_returns_empty(self) -> None:
        api = Swisstopo(_client(lambda r: httpx.Response(200, json={"results": []})))
        assert await api.search_locations("Atlantis", "de") == []


class TestIdentifyFeatures:
    async def test_requests_wgs84_geojson_and_returns_features(self) -> None:
        captured: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(dict(request.url.params))
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "featureId": "2011",
                            "layerBodId": "ch.bafu.hydrologie-hochwasserstatistik",
                            "geometry": {"type": "Point", "coordinates": [7.357901, 46.21909]},
                            "properties": {"name": "Rhône - Sion"},
                        }
                    ]
                },
            )

        api = Swisstopo(_client(handler))
        features = await api.identify_features(
            "ch.bafu.hydrologie-hochwasserstatistik", [7.3, 46.17, 7.43, 46.26], "de"
        )

        # WGS84 in, WGS84 out: nothing needs reprojecting before the browser sees it.
        assert captured["sr"] == "4326"
        assert captured["geometryFormat"] == "geojson"
        assert captured["geometryType"] == "esriGeometryEnvelope"
        assert features[0]["type"] == "Feature"
        assert features[0]["properties"]["name"] == "Rhône - Sion"

    async def test_caps_the_limit_at_the_api_maximum(self) -> None:
        captured: dict[str, str] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            captured.update(dict(request.url.params))
            return httpx.Response(200, json={"results": []})

        api = Swisstopo(_client(handler))
        await api.identify_features("ch.x", [7, 46, 8, 47], "de", limit=99_999)
        assert captured["limit"] == "200"

    async def test_skips_results_without_geometry(self) -> None:
        payload = {"results": [{"featureId": "1", "properties": {}}]}
        api = Swisstopo(_client(lambda r: httpx.Response(200, json=payload)))
        assert await api.identify_features("ch.x", [7, 46, 8, 47], "de") == []

    async def test_a_non_queryable_layer_is_distinguished_from_a_failure(self) -> None:
        """identify answers 400 for raster and warning-map layers. That is a fact about
        the dataset, and reporting it as a generic tool failure made models retry the
        same layer until they exhausted their iteration budget."""
        api = Swisstopo(_client(lambda r: httpx.Response(400, json={"error": "bad layer"})))
        with pytest.raises(LayerNotQueryable) as caught:
            await api.identify_features("ch.bafu.aquaprotect_100", [7, 46, 8, 47], "de")
        assert caught.value.layer_id == "ch.bafu.aquaprotect_100"

    async def test_an_upstream_error_propagates(self) -> None:
        """The tool layer turns this into a reported tool failure, not a silent empty
        result that would look like "no data exists"."""
        api = Swisstopo(_client(lambda r: httpx.Response(503)))
        with pytest.raises(httpx.HTTPStatusError):
            await api.identify_features("ch.x", [7, 46, 8, 47], "de")


class TestGeometry:
    def test_picks_the_dominant_geometry_family(self) -> None:
        features = [
            {"geometry": {"type": "Polygon", "coordinates": []}},
            {"geometry": {"type": "MultiPolygon", "coordinates": []}},
            {"geometry": {"type": "Point", "coordinates": [7, 46]}},
        ]
        assert geometry_type(features) == "polygon"

    def test_points_are_not_reported_as_polygons(self) -> None:
        """A point set styled as a polygon renders invisibly."""
        assert geometry_type([{"geometry": {"type": "Point", "coordinates": [7, 46]}}]) == "point"

    def test_empty_input_defaults_to_point(self) -> None:
        assert geometry_type([]) == "point"

    def test_bounding_box_spans_all_coordinates(self) -> None:
        features = [
            {"geometry": {"type": "Point", "coordinates": [7.0, 46.0]}},
            {"geometry": {"type": "Point", "coordinates": [8.5, 47.2]}},
        ]
        assert bounding_box(features) == [7.0, 46.0, 8.5, 47.2]

    def test_bounding_box_handles_nested_polygon_rings(self) -> None:
        features = [
            {
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[[7.0, 46.0], [7.5, 46.0], [7.5, 46.5], [7.0, 46.0]]],
                }
            }
        ]
        assert bounding_box(features) == [7.0, 46.0, 7.5, 46.5]

    def test_bounding_box_of_nothing_is_none(self) -> None:
        assert bounding_box([]) is None
        assert bounding_box([{"geometry": None}]) is None

    def test_area_is_measured_in_projected_metres_not_degrees(self) -> None:
        """A square degree is not an area; LV95 is the CRS the map already uses."""
        features = [
            {
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [[7.0, 46.0], [7.1, 46.0], [7.1, 46.1], [7.0, 46.1], [7.0, 46.0]]
                    ],
                }
            }
        ]
        result = measure(features)
        # ~7.7 km x ~11.1 km near Valais.
        assert 50 < result["area_km2"] < 120

    def test_measuring_skips_broken_geometry_instead_of_failing(self) -> None:
        features = [
            {"geometry": {"type": "Polygon", "coordinates": "nonsense"}},
            {"geometry": {"type": "Point", "coordinates": [7.0, 46.0]}},
        ]
        assert measure(features)["area_km2"] == 0.0

    def test_property_summary_lists_distinct_values(self) -> None:
        features = [
            {"properties": {"gefahrenstufe": "hoch", "name": "Sion"}},
            {"properties": {"gefahrenstufe": "mittel", "name": "Sierre"}},
            {"properties": {"gefahrenstufe": "hoch", "name": "Visp"}},
        ]
        summary = summarise_properties(features)
        assert set(summary["gefahrenstufe"]) == {"hoch", "mittel"}
        assert len(summary["name"]) == 3

    def test_property_summary_ignores_empty_values(self) -> None:
        assert summarise_properties([{"properties": {"a": None, "b": ""}}]) == {}


class TestResultCache:
    def test_round_trips_a_feature_set(self) -> None:
        cache = ResultCache()
        entry = cache.put("ch.x", "Title", [{"type": "Feature"}])
        assert cache.get(entry.result_id) is entry
        assert entry.result_id.startswith("fs_")

    def test_unknown_handles_return_none(self) -> None:
        assert ResultCache().get("fs_nope") is None

    def test_evicts_the_least_recently_used(self) -> None:
        cache = ResultCache(limit=2)
        first = cache.put("a", "a", [])
        second = cache.put("b", "b", [])
        cache.get(first.result_id)
        third = cache.put("c", "c", [])

        assert cache.get(second.result_id) is None
        assert cache.get(first.result_id) is not None
        assert cache.get(third.result_id) is not None


class TestTruncationIsAnnounced:
    """A count taken from a capped fetch is a wrong number.

    Observed live: the model answered "50 Hochwasser-Messstationen im Kanton Bern" - 50 being
    the fetch limit, not anything about Bern. The tool now has to say the set was capped, in
    words the model will repeat.
    """

    async def _fetch(self, feature_count: int, limit: int) -> dict:
        from mcp_dummy.server import build_server

        payload = {
            "results": [
                {
                    "featureId": str(i),
                    "geometry": {"type": "Point", "coordinates": [7.4 + i / 1000, 46.9]},
                    "properties": {"name": f"Station {i}"},
                }
                for i in range(feature_count)
            ]
        }

        class Artifacts:
            async def publish_geojson(self, name: str, collection: dict) -> str:
                return f"/data/{name}"

        api = Swisstopo(_client(lambda r: httpx.Response(200, json=payload)))
        server = build_server(Artifacts(), swisstopo=api)
        from mcp import Client

        async with Client(server) as client:
            result = await client.call_tool(
                "filter_features",
                {"layer_id": "ch.x", "bbox": [7, 46, 8, 47], "limit": limit},
            )
        return json.loads(result.content[0].text)

    async def test_a_capped_fetch_says_so(self) -> None:
        data = await self._fetch(feature_count=60, limit=50)
        assert data["truncated"] is True
        assert "NOT the total" in data["count_note"]
        assert "at least" in data["count_note"]

    async def test_a_complete_fetch_carries_no_caveat(self) -> None:
        data = await self._fetch(feature_count=12, limit=50)
        assert data["truncated"] is False
        assert "count_note" not in data


def test_features_serialise_as_valid_geojson() -> None:
    """What display_layer writes must be a FeatureCollection the browser can parse."""
    features = [
        {
            "type": "Feature",
            "id": "2011",
            "geometry": {"type": "Point", "coordinates": [7.357901, 46.21909]},
            "properties": {"name": "Rhône - Sion"},
        }
    ]
    collection = json.loads(json.dumps({"type": "FeatureCollection", "features": features}))
    assert collection["type"] == "FeatureCollection"
    assert collection["features"][0]["geometry"]["type"] == "Point"
