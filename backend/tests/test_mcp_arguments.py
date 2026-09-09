"""Repairs for the argument shapes the weaker models actually emit.

Every case here was observed in swisstopo's 2026-09-08 test round rather than imagined:
Apertus sent `place` as the `{name, kind}` object search_locations had returned, and
filled every optional property with null, then repeated the identical call.
"""

from __future__ import annotations

from app.mcp.arguments import normalise_arguments

# Copied from what geosearch actually serves, not hand-written. Every optional parameter
# is an anyOf union with null, which is why an earlier version of this file - which wrote
# `{"type": "string"}` for `place` - passed while the repair never fired in production.
FILTER_SCHEMA = {
    "type": "object",
    "properties": {
        "layer_id": {"type": "string"},
        "place": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
        "place_kind": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
        "bbox": {
            "anyOf": [{"items": {"type": "number"}, "type": "array"}, {"type": "null"}],
            "default": None,
        },
        "filters": {"anyOf": [{"type": "array"}, {"type": "null"}], "default": None},
    },
    "required": ["layer_id"],
}

RESULT_SCHEMA = {
    "type": "object",
    "properties": {
        "result_id": {"type": "string"},
        "lang": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None},
    },
    "required": ["result_id"],
}


class TestNormaliseArguments:
    def test_flattens_a_place_object_into_name_and_kind(self) -> None:
        result = normalise_arguments(
            {"layer_id": "ch.bafu.x", "place": {"name": "Bern", "kind": "kanton"}},
            FILTER_SCHEMA,
        )
        assert result == {"layer_id": "ch.bafu.x", "place": "Bern", "place_kind": "kanton"}

    def test_keeps_an_explicit_place_kind_over_the_nested_one(self) -> None:
        result = normalise_arguments(
            {
                "layer_id": "ch.bafu.x",
                "place": {"name": "Bern", "kind": "kanton"},
                "place_kind": "gemeinde",
            },
            FILTER_SCHEMA,
        )
        assert result["place"] == "Bern"
        assert result["place_kind"] == "gemeinde"

    def test_drops_a_null_optional_argument(self) -> None:
        assert normalise_arguments({"result_id": "r1", "lang": None}, RESULT_SCHEMA) == {
            "result_id": "r1"
        }

    def test_keeps_a_null_required_argument_so_the_tool_reports_it(self) -> None:
        """Dropping it would turn a wrong call into a bare "field required", and the model
        needs to see which argument it left empty."""
        assert normalise_arguments({"result_id": None}, RESULT_SCHEMA) == {"result_id": None}

    def test_unwraps_a_single_element_list_where_a_string_is_wanted(self) -> None:
        result = normalise_arguments({"layer_id": ["ch.bafu.x"]}, FILTER_SCHEMA)
        assert result["layer_id"] == "ch.bafu.x"

    def test_leaves_a_longer_list_alone_where_a_string_is_wanted(self) -> None:
        """Two layer ids is a different mistake, and picking one of them would be a guess
        about which dataset the user asked for."""
        result = normalise_arguments({"layer_id": ["a", "b"]}, FILTER_SCHEMA)
        assert result["layer_id"] == ["a", "b"]

    def test_wraps_a_scalar_where_an_array_is_wanted(self) -> None:
        one = {"field": "objektart", "operator": "equals", "value": "Park"}
        result = normalise_arguments({"layer_id": "ch.bafu.x", "filters": one}, FILTER_SCHEMA)
        assert result["filters"] == [one]

    def test_leaves_a_valid_call_untouched(self) -> None:
        arguments = {"layer_id": "ch.bafu.x", "place": "Bern", "place_kind": "kanton"}
        assert normalise_arguments(dict(arguments), FILTER_SCHEMA) == arguments

    def test_leaves_an_unknown_argument_alone(self) -> None:
        """The schema says nothing about it, so there is nothing to repair it towards."""
        result = normalise_arguments({"layer_id": "ch.bafu.x", "invented": None}, FILTER_SCHEMA)
        assert result["invented"] is None

    def test_survives_a_schema_it_does_not_understand(self) -> None:
        assert normalise_arguments({"a": 1}, {}) == {"a": 1}

    def test_does_not_mutate_the_arguments_it_was_given(self) -> None:
        arguments = {"layer_id": "ch.bafu.x", "place": {"name": "Bern", "kind": "kanton"}}
        normalise_arguments(arguments, FILTER_SCHEMA)
        assert arguments["place"] == {"name": "Bern", "kind": "kanton"}


class TestNullableSchemas:
    """Pydantic renders every optional parameter as an anyOf union with null. Reading
    `type` directly finds nothing there, so the repair silently did nothing for exactly
    the parameters the weaker models get wrong - measured against Apertus, which sent
    place={'name': 'Bern', 'kind': 'kanton'} and had it passed straight through."""

    def test_resolves_a_nullable_string(self) -> None:
        from app.mcp.arguments import _declared_types

        assert _declared_types({"anyOf": [{"type": "string"}, {"type": "null"}]}) == {"string"}

    def test_resolves_a_nullable_array(self) -> None:
        from app.mcp.arguments import _declared_types

        declared = {"anyOf": [{"items": {"type": "number"}, "type": "array"}, {"type": "null"}]}
        assert _declared_types(declared) == {"array"}

    def test_resolves_a_plain_type_and_a_type_list(self) -> None:
        from app.mcp.arguments import _declared_types

        assert _declared_types({"type": "string"}) == {"string"}
        assert _declared_types({"type": ["string", "null"]}) == {"string"}

    def test_survives_a_property_with_no_type_at_all(self) -> None:
        from app.mcp.arguments import _declared_types

        assert _declared_types({"description": "free form"}) == set()

    def test_the_apertus_shape_is_repaired_against_the_real_schema(self) -> None:
        """The exact call Apertus made, against the schema geosearch actually serves."""
        result = normalise_arguments(
            {"layer_id": "ch.bafu.x", "place": {"name": "Bern", "kind": "kanton"}},
            FILTER_SCHEMA,
        )
        assert result == {"layer_id": "ch.bafu.x", "place": "Bern", "place_kind": "kanton"}

    def test_the_fixture_keeps_the_union_shape_production_serves(self) -> None:
        """Guards the trap itself: simplifying these fixtures to a plain {"type": "string"}
        is what let the repair pass its tests while doing nothing on the real server."""
        assert "anyOf" in FILTER_SCHEMA["properties"]["place"]
        assert "anyOf" in FILTER_SCHEMA["properties"]["bbox"]
        assert "anyOf" in RESULT_SCHEMA["properties"]["lang"]
