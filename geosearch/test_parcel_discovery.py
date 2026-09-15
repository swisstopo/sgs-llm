"""Parcel regressions through the connector and the persisted-index search path."""

import asyncio

import pytest

from .catalog_terms import alias_matches
from .index import GeoIndex, build
from .rerank import _render
from .swisstopo import Swisstopo
from .test_geosearch import StubEmbedder, _layer

PARCEL = "ch.swisstopo-vd.amtliche-vermessung"
MAP = "ch.kantone.cadastralwebmap-farbe"


@pytest.mark.parametrize(
    "query,expected",
    [
        ("CH 3435 4679 1597", "CH343546791597"),
        ("ch\u00a03435\t4679\n1597", "CH343546791597"),
        ("CH343546791597", "CH343546791597"),
        ("Seftigenstrasse 264, 3084 Wabern", "Seftigenstrasse 264, 3084 Wabern"),
        ("Belp 20", "Belp 20"),
        ("CH 3435 4679", "CH 3435 4679"),
        ("Parzelle CH 3435 4679 1597", "Parzelle CH 3435 4679 1597"),
    ],
)
def test_egrid_normalizes_only_complete_identifiers(query, expected):
    api = Swisstopo()
    sent = []

    async def get(url, params):
        sent.append(params["searchText"])
        return {"results": []}

    api._get = get
    asyncio.run(api.geocode_location(query))
    assert sent == [expected]


@pytest.fixture(scope="module")
def parcel_index(tmp_path_factory):
    path = tmp_path_factory.mktemp("parcel-index")
    # Opaque title and empty metadata reproduce the published report's indexing gap.
    # Aliases apply at read time, so no index rebuild or changed vectors are required.
    layers = [_layer(PARCEL, "OpenData-AV", ""), _layer(MAP, "CadastralWebMap", "")]
    layers += [_layer(f"ch.noise.{i}", f"noise {i}", "") for i in range(40)]
    build(path, layers, [], StubEmbedder())
    return GeoIndex(path, StubEmbedder())


@pytest.mark.parametrize(
    "query", ["Parzellen", "parcelles", "cadastral parcels", "particelle", "EGRID"]
)
def test_parcel_synonyms_reach_candidates_with_sparse_metadata(parcel_index, query):
    hits = parcel_index.search_layers(query, limit=8)
    assert hits[0].row["layer_id"] == PARCEL
    assert "parcelles" in hits[0].row["search_terms"]
    rendered = _render([hits[0].row])
    assert "Catalogue search aliases:" in rendered
    assert "parcelles" in rendered


@pytest.mark.parametrize(
    "query", ["Katasterplan", "plan cadastral", "cadastral map", "mappa catastale"]
)
def test_official_plan_is_distinct_from_parcel_geometry(parcel_index, query):
    assert parcel_index.search_layers(query, limit=8)[0].row["layer_id"] == MAP


def test_aliases_use_word_boundaries():
    assert not alias_matches("parcelled delivery logistics", PARCEL)
    assert not alias_matches("EGRID-like nonsense", "ch.unknown")
