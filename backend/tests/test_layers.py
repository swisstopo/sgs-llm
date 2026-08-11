"""LayerSpec extraction from tool output.

This is the boundary with a server we do not control, so the cases that matter are the
malformed ones. A layer the frontend would discard is dropped here instead, and
a bad bbox must not send the user's map to the middle of nowhere.
"""

from __future__ import annotations

from typing import Any

from app.agent.layers import extract_catalog_layers, extract_focus_bbox, extract_layers


def test_finds_a_layer_nested_in_a_tool_result() -> None:
    layers = extract_layers(
        {
            "layer": {
                "id": "fs_1",
                "name": "Hochwasser",
                "format": "geojson",
                "url": "https://example.test/a.geojson",
                "geometry_type": "polygon",
                "feature_count": 5,
                "bbox": [7.0, 46.0, 8.0, 46.5],
            }
        }
    )
    assert len(layers) == 1
    assert layers[0].name == "Hochwasser"
    assert layers[0].feature_count == 5


def test_resolves_a_relative_url_against_the_public_origin() -> None:
    layers = extract_layers(
        {"url": "/data/x.geojson", "geometry_type": "point", "name": "x", "id": "x"},
        base_url="https://denpw8uo5zpkl.cloudfront.net",
    )
    assert layers[0].url == "https://denpw8uo5zpkl.cloudfront.net/data/x.geojson"


def test_leaves_a_presigned_absolute_url_alone() -> None:
    url = "https://sgs-llm-data-259789526488.s3.eu-central-1.amazonaws.com/a.geojson?X-Amz-Signature=abc"
    layers = extract_layers(
        {"url": url, "geometry_type": "polygon", "id": "a", "name": "a"},
        base_url="https://example.test",
    )
    assert layers[0].url == url


def test_extracts_mvt_tile_templates_and_zoom_range() -> None:
    layers = extract_layers(
        {
            "id": "roads",
            "name": "Roads",
            "format": "mvt",
            "url": "/data/tiles/token/{z}/{x}/{y}.mvt",
            "dispose_url": "/data/layers/token",
            "url_expires_at": "2026-08-11T10:00:00Z",
            "geometry_type": "line",
            "min_zoom": 0,
            "max_zoom": 16,
        },
        base_url="https://example.test",
    )

    assert len(layers) == 1
    layer = layers[0]
    assert layer.url == "https://example.test/data/tiles/token/{z}/{x}/{y}.mvt"
    assert layer.dispose_url == "/data/layers/token"
    assert (layer.min_zoom, layer.max_zoom) == (0, 16)


def test_extraction_still_ignores_unrelated_tool_result_fields() -> None:
    layers = extract_layers(
        {
            "id": "roads",
            "name": "Roads",
            "format": "geojson",
            "url": "/data/roads.geojson",
            "geometry_type": "line",
            "provider_metadata": {"request_id": "req-1"},
        },
        base_url="https://example.test",
    )

    assert len(layers) == 1
    assert layers[0].url == "https://example.test/data/roads.geojson"


def test_infers_the_format_from_the_extension() -> None:
    assert extract_layers({"url": "https://x.test/a.geojson", "geometry_type": "point"})
    assert extract_layers(
        {
            "url": "https://x.test/a/{z}/{x}/{y}.mvt",
            "geometry_type": "point",
            "min_zoom": 0,
            "max_zoom": 16,
        }
    )


def test_ignores_a_url_with_no_recognisable_format() -> None:
    assert extract_layers({"url": "https://x.test/page.html", "geometry_type": "point"}) == []


def test_rejects_a_bbox_that_is_not_wgs84() -> None:
    """LV95 metres in a WGS84 field would zoom the map off the planet."""
    layers = extract_layers(
        {
            "url": "https://x.test/a.geojson",
            "geometry_type": "polygon",
            "bbox": [2600000, 1200000, 2610000, 1210000],
        }
    )
    assert len(layers) == 1
    assert layers[0].bbox is None


def test_ignores_a_malformed_bbox() -> None:
    layers = extract_layers(
        {"url": "https://x.test/a.geojson", "geometry_type": "point", "bbox": [1, 2, 3]}
    )
    assert layers[0].bbox is None


def test_normalises_geometry_aliases() -> None:
    for given, expected in [
        ("MultiPolygon", "polygon"),
        ("LineString", "line"),
        ("MultiPoint", "point"),
        ("POINT", "point"),
    ]:
        layers = extract_layers({"url": "https://x.test/a.geojson", "geometry_type": given})
        assert layers[0].geometry_type == expected


def test_a_missing_geometry_type_still_produces_a_layer() -> None:
    """Dropping it would mean no layer at all for a server that omits the field."""
    layers = extract_layers({"url": "https://x.test/a.geojson", "name": "x"})
    assert len(layers) == 1
    assert layers[0].geometry_type == "polygon"


def test_deduplicates_by_url() -> None:
    payload = {
        "first": {"url": "https://x.test/a.geojson", "geometry_type": "point"},
        "second": {"url": "https://x.test/a.geojson", "geometry_type": "point"},
    }
    assert len(extract_layers(payload)) == 1


def test_accepts_a_list_of_layers() -> None:
    payload = {
        "layers": [
            {"url": "https://x.test/a.geojson", "geometry_type": "point", "id": "a"},
            {"url": "https://x.test/b.geojson", "geometry_type": "polygon", "id": "b"},
        ]
    }
    assert len(extract_layers(payload)) == 2


def test_accepts_alternative_key_names() -> None:
    """A foreign MCP server may call them href/title rather than url/name."""
    layers = extract_layers(
        {"href": "https://x.test/a.geojson", "title": "Solarpotenzial", "geometry_type": "polygon"}
    )
    assert layers[0].name == "Solarpotenzial"


def test_ignores_non_layer_payloads() -> None:
    assert extract_layers({"places": [{"name": "Sion", "bbox": [7, 46, 7.5, 46.3]}]}) == []
    assert extract_layers({"feature_count": 0, "note": "nothing here"}) == []
    assert extract_layers(None) == []
    assert extract_layers("a string") == []


def test_caps_the_number_of_layers_per_answer() -> None:
    payload = {
        "layers": [
            {"url": f"https://x.test/{i}.geojson", "geometry_type": "point", "id": str(i)}
            for i in range(20)
        ]
    }
    assert len(extract_layers(payload)) == 6


def test_carries_style_hint_and_attribution_through() -> None:
    layers = extract_layers(
        {
            "url": "https://x.test/a.geojson",
            "geometry_type": "polygon",
            "attribution": "swisstopo / geo.admin.ch",
            "style_hint": {"fill_color": "#1c64f2", "opacity": 0.4},
        }
    )
    assert layers[0].attribution == "swisstopo / geo.admin.ch"
    assert layers[0].style_hint is not None
    assert layers[0].style_hint.fill_color == "#1c64f2"


class TestCatalogLayers:
    """Official layers are *named*, not shipped - the fix for raster data.

    The distinguishing signal is a `ch.*` id with no fetchable URL, so the two extractors
    never claim the same tool output.
    """

    def test_finds_a_catalog_reference(self) -> None:
        refs = extract_catalog_layers(
            {
                "catalog_layer": {
                    "id": "ch.bafu.aquaprotect_100",
                    "name": "Überschwemmung Aquaprotect 100",
                    "opacity": 0.6,
                    "attribution": "swisstopo / geo.admin.ch",
                }
            }
        )
        assert len(refs) == 1
        assert refs[0].id == "ch.bafu.aquaprotect_100"
        assert refs[0].opacity == 0.6

    def test_search_results_are_not_display_instructions(self) -> None:
        """The bug this check exists for.

        `search_layers` returns candidates shaped exactly like a catalog ref. Matching them
        put six layers on the user's map for a question that only asked what data exists,
        with no display tool called at all. Display must be explicit.
        """
        search_result = {
            "layers": [
                {"layer_id": "ch.bafu.aquaprotect_100", "title": "Aquaprotect 100"},
                {"layer_id": "ch.bafu.hydrologie-hochwasserstatistik", "title": "Statistik"},
            ]
        }
        assert extract_catalog_layers(search_result) == []

    def test_a_bare_layer_id_under_the_display_key_is_enough(self) -> None:
        refs = extract_catalog_layers({"catalog_layer": {"layer_id": "ch.are.bauzonen"}})
        assert [r.id for r in refs] == ["ch.are.bauzonen"]

    def test_accepts_a_list_under_the_display_key(self) -> None:
        refs = extract_catalog_layers({"catalog_layers": [{"id": "ch.a.b"}, {"id": "ch.c.d"}]})
        assert [r.id for r in refs] == ["ch.a.b", "ch.c.d"]

    def test_ignores_ids_that_are_not_official_layers(self) -> None:
        for bad in ("fs_abc123", "agent-layer-0", "CH.BAFU.Upper"):
            assert extract_catalog_layers({"catalog_layer": {"id": bad}}) == []

    def test_a_produced_layer_is_not_mistaken_for_a_catalog_reference(self) -> None:
        """It has a fetchable URL, so it belongs to extract_layers."""
        payload = {
            "catalog_layer": {
                "id": "ch.bafu.something",
                "url": "https://x.test/a.geojson",
                "geometry_type": "point",
            }
        }
        assert extract_catalog_layers(payload) == []
        assert len(extract_layers(payload)) == 1

    def test_deduplicates_by_id(self) -> None:
        payload = {
            "a": {"catalog_layer": {"id": "ch.x.y"}},
            "b": {"catalog_layer": {"id": "ch.x.y"}},
        }
        assert len(extract_catalog_layers(payload)) == 1

    def test_ignores_non_layer_payloads(self) -> None:
        assert extract_catalog_layers({"places": [{"name": "Sion"}]}) == []
        assert extract_catalog_layers(None) == []


class TestFocusBBox:
    def test_finds_a_focus_bbox(self) -> None:
        assert extract_focus_bbox({"focus_bbox": [7.29, 46.91, 7.5, 46.99]}) == (
            7.29,
            46.91,
            7.5,
            46.99,
        )

    def test_finds_it_nested(self) -> None:
        assert extract_focus_bbox({"result": {"focus_bbox": [7.0, 46.0, 8.0, 47.0]}}) is not None

    def test_rejects_a_non_wgs84_focus_bbox(self) -> None:
        """LV95 metres would send the camera off the planet."""
        assert extract_focus_bbox({"focus_bbox": [2600000, 1200000, 2610000, 1210000]}) is None

    def test_absent_is_none(self) -> None:
        assert extract_focus_bbox({"layer": {"id": "ch.x.y"}}) is None


def test_per_model_prompt_selection() -> None:
    from app.agent import prompts

    assert prompts.prompt_template_for("anything") is prompts._BASE

    variant = prompts._BASE + "\n\nExtra guidance for {language} speakers is not needed."
    original = prompts.MODEL_PROMPTS
    try:
        prompts.MODEL_PROMPTS = {"mistral": variant}
        # Matched as a case-insensitive substring of the full Bedrock id.
        assert prompts.prompt_template_for("mistral.ministral-3-14b-instruct") is variant
        assert prompts.prompt_template_for("MISTRAL.Whatever") is variant
        assert prompts.prompt_template_for("eu.anthropic.claude-sonnet-4-6") is prompts._BASE
        rendered = prompts.system_prompt("de", model_id="mistral.ministral-3-14b-instruct")
        assert "German (Deutsch)" in rendered
        assert "Extra guidance" in rendered
    finally:
        prompts.MODEL_PROMPTS = original


def test_an_inverted_bbox_is_ordered_not_emitted_as_is() -> None:
    """The protocol says [minLon, minLat, maxLon, maxLat]; an inverted box would make the
    client fit an empty extent."""
    assert extract_focus_bbox({"focus_bbox": [10.0, 47.5, 5.0, 46.0]}) == (5.0, 46.0, 10.0, 47.5)


def test_out_of_range_opacity_is_clamped_not_dropped() -> None:
    """docs/protocol/server-events.schema.json declares opacity 0..1, and emitted frames
    are validated against it. Clamping keeps the frame valid without dropping the layer."""
    refs = extract_catalog_layers({"catalog_layer": {"id": "ch.x", "opacity": 50}})
    assert refs[0].opacity == 1.0
    refs = extract_catalog_layers({"catalog_layer": {"id": "ch.y", "opacity": -3}})
    assert refs[0].opacity == 0.0
    # A bool is an int in Python; it is not an opacity.
    refs = extract_catalog_layers({"catalog_layer": {"id": "ch.z", "opacity": True}})
    assert refs[0].opacity is None


def test_an_out_of_range_style_opacity_is_clamped() -> None:
    layers = extract_layers(
        {
            "layer": {
                "id": "l1",
                "name": "L",
                "format": "geojson",
                "url": "https://x/y.geojson",
                "geometry_type": "point",
                "style_hint": {"opacity": 9},
            }
        }
    )
    assert layers[0].style_hint is not None
    assert layers[0].style_hint.opacity == 1.0


def test_a_broken_prompt_template_is_rejected_up_front() -> None:
    """A stray brace must not become "every turn fails" on a deployed task."""
    import pytest

    from app.agent import prompts

    original = prompts.MODEL_PROMPTS
    try:
        prompts.MODEL_PROMPTS = {"x": "no placeholder here"}
        with pytest.raises(ValueError, match="does not use"):
            prompts._check_templates()

        prompts.MODEL_PROMPTS = {"x": "{language} and a {stray} brace"}
        with pytest.raises(ValueError, match="not formattable"):
            prompts._check_templates()
    finally:
        prompts.MODEL_PROMPTS = original
        prompts._check_templates()


def test_a_point_bbox_is_padded_to_a_viewport() -> None:
    bbox = extract_focus_bbox({"focus_bbox": [7.4, 46.9, 7.4, 46.9]})
    assert bbox is not None
    west, south, east, north = bbox
    assert east > west and north > south
    assert round(east - west, 4) == 0.04


def test_layer_ids_stay_unique_across_tool_calls() -> None:
    """The client keys layers on id, so a collision means the second one never renders."""
    first = {
        "layer": {
            "name": "A",
            "format": "geojson",
            "url": "https://x/a.geojson",
            "geometry_type": "point",
        }
    }
    second = {
        "layer": {
            "name": "B",
            "format": "geojson",
            "url": "https://x/b.geojson",
            "geometry_type": "point",
        }
    }
    a = extract_layers(first, start_index=0)
    b = extract_layers(second, start_index=len(a))
    assert [s.id for s in a] != [s.id for s in b]


def test_padding_cannot_push_a_bbox_outside_wgs84() -> None:
    assert extract_focus_bbox({"focus_bbox": [7.0, 90.0, 7.0, 90.0]}) == (6.98, 89.98, 7.02, 90.0)
    assert extract_focus_bbox({"focus_bbox": [180.0, 46.0, 180.0, 46.0]}) == (
        179.98,
        45.98,
        180.0,
        46.02,
    )


def test_deeply_nested_tool_output_does_not_blow_the_stack() -> None:
    deep: Any = {"focus_bbox": [1.0, 2.0, 3.0, 4.0]}
    for _ in range(5000):
        deep = {"wrapper": deep}
    assert extract_focus_bbox(deep) is None
    assert extract_catalog_layers(deep) == []
