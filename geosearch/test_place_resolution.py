"""Scope, name qualifiers and ambiguous-place recovery at the MCP boundary."""

import asyncio

import pytest
from mcp import Client

from .index import GeoIndex, build
from .places import DivisionLookupError
from .server import build_server
from .test_geosearch import StubEmbedder, _layer
from .test_server import RecordingArtifacts, StubBoundaries, StubSwisstopo, _point


@pytest.fixture(scope="module")
def places(tmp_path_factory):
    path = tmp_path_factory.mktemp("division-resolution")
    records = []
    for name, kind, canton in [
        ("Bern", "kanton", "BE"),
        ("Bern", "gemeinde", "BE"),
        ("Genève", "gemeinde", "GE"),
        ("Lugano", "gemeinde", "TI"),
        ("Buchs", "gemeinde", "SG"),
        ("Buchs", "gemeinde", "ZH"),
    ]:
        records.append(
            {
                "name": name,
                "kind": kind,
                "canton": canton,
                "bbox": [7, 46, 8, 47],
                "layer_id": "ch.boundary",
                "s3_key": f"divisions/{kind}/{canton}/{name}.geojson",
            }
        )
    build(path, [_layer("ch.test", "Test", "")], records, StubEmbedder())
    return GeoIndex(path, StubEmbedder())


@pytest.mark.parametrize(
    "name,expected,kind",
    [
        ("Stadt Bern", "Bern", "gemeinde"),
        ("Kanton Bern", "Bern", "kanton"),
        ("Ville de Genève", "Genève", "gemeinde"),
        ("Città di Lugano", "Lugano", "gemeinde"),
        ("City of Bern", "Bern", "gemeinde"),
    ],
)
def test_lookup_and_search_share_administrative_qualifiers(
    places, name, expected, kind
):
    assert places.division_by_name(name)["name"] == expected
    assert places.division_by_name(name)["kind"] == kind
    hits = places.search_divisions(name)
    assert hits[0].row["name"] == expected
    assert all(h.row["kind"] == kind for h in hits)


def test_conflicting_explicit_scope_is_not_overridden(places):
    with pytest.raises(DivisionLookupError, match="conflicts"):
        places.division_by_name("Stadt Bern", "kanton")
    assert places.search_divisions("Stadt Bern", kinds=["kanton"]) == []


def test_same_name_and_kind_can_be_disambiguated_by_reference(places):
    with pytest.raises(DivisionLookupError) as error:
        places.division_by_name("Buchs", "gemeinde")
    rows = error.value.candidates
    assert {r["canton"] for r in rows} == {"SG", "ZH"}
    wanted = next(r for r in rows if r["canton"] == "ZH")
    row = places.division_by_name("", division_ref=wanted["division_ref"])
    assert row["canton"] == "ZH"
    with pytest.raises(DivisionLookupError, match="conflicts"):
        places.division_by_name("Bern", division_ref=wanted["division_ref"])


def test_unknown_or_approximate_name_never_silently_fetches_another_place(places):
    assert places.division_by_name("Berne", "gemeinde") is None
    with pytest.raises(DivisionLookupError, match="Unknown"):
        places.division_by_name("", division_ref="../../unknown.geojson")


def test_mcp_ambiguity_does_not_fetch_and_reference_recovers(places):
    api = StubSwisstopo([_point(1, x=7.5)])
    artifacts = RecordingArtifacts()

    async def run():
        server = build_server(places, api, artifacts, StubBoundaries())
        async with Client(server) as client:
            found = await client.call_tool("search_locations", {"query": "Stadt Bern"})
            ref = found.structured_content["places"][0]["division_ref"]
            ambiguous = await client.call_tool(
                "filter_features", {"layer_id": "ch.test", "place": "Bern"}
            )
            data = ambiguous.structured_content
            assert len(data["candidates"]) == 2
            assert not api.fetch_kwargs
            assert "result_id" not in data
            displayed = await client.call_tool("display_division", {"name": "Bern"})
            assert displayed.structured_content["candidates"]
            assert not artifacts.calls
            chosen = await client.call_tool(
                "filter_features", {"layer_id": "ch.test", "place_ref": ref}
            )
            assert chosen.structured_content["clipped_to"] == "gemeinde Bern"
            assert chosen.structured_content["feature_count"] == 1
            shown = await client.call_tool("display_division", {"division_ref": ref})
            assert shown.structured_content["layer"]["name"] == "Bern"

    asyncio.run(run())
