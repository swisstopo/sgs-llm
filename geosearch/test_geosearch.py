"""Checks for the parts that fail silently.

Ranking quality is not asserted here - it is a property of the embedding model, and a
test that pins it would only ever break when the model was upgraded. What is asserted is
the machinery around it, where a bug produces plausible-looking wrong answers rather
than an error: dropped Z ordinates, a reranker that swallows its own parse failure, a
weighted score that quietly ignores half its input.

    .venv/bin/python -m pytest geosearch/test_geosearch.py -q
"""

from __future__ import annotations

import asyncio
import json
import zlib
from datetime import UTC, datetime

import numpy as np
import pytest

from .build import _kind, _s3_key, _slug
from .index import GeoIndex, build, confidence
from .layer_publisher import PublishedLayer
from .limits import FetchResult
from .rerank import _parse
from .swisstopo import DivisionLayer, Swisstopo, feature_name, to_2d


class StubEmbedder:
    """Deterministic character-trigram vectors. No network, no model.

    Embedding is a Bedrock call now, and a test that calls Bedrock fails in CI, where the
    job has no role to assume and no reason to have one. Trigram overlap is not semantic -
    "forêt" and "Wald" are unrelated here, and any test that needed them to be alike would
    be testing Cohere rather than this code - but it does reproduce the two lexical
    properties the fixtures rely on: an exact title matches itself at 1.0, and "Zurich"
    lands nearer "Zürich" than "Baar".

    crc32 rather than hash(): str hashing is salted per process, so the same text would
    embed differently between runs and a failure would not reproduce.
    """

    model_name = "stub-trigram"
    dim = 256

    def _one(self, text: str) -> np.ndarray:
        vector = np.zeros(self.dim, dtype=np.float32)
        padded = f"  {text.lower()}  "
        for i in range(len(padded) - 2):
            vector[zlib.crc32(padded[i : i + 3].encode()) % self.dim] += 1.0
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm else vector

    def encode_documents(self, texts) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        return np.stack([self._one(t) for t in texts])

    def encode_query(self, text: str) -> np.ndarray:
        return self._one(text)


# ------------------------------------------------------------------ geometry


def test_to_2d_strips_z_at_every_nesting_depth():
    # swissBOUNDARIES3D is 3D; OpenLayers reads the third ordinate as data and
    # reprojects nonsense rather than failing, so a missed case is invisible on the map.
    assert to_2d({"type": "Point", "coordinates": [8.5, 47.4, 430.0]})[
        "coordinates"
    ] == [8.5, 47.4]

    line = to_2d(
        {"type": "LineString", "coordinates": [[8.5, 47.4, 1.0], [8.6, 47.5, 2.0]]}
    )
    assert line["coordinates"] == [[8.5, 47.4], [8.6, 47.5]]

    multi = to_2d(
        {
            "type": "MultiPolygon",
            "coordinates": [[[[8.5, 47.4, 1.0], [8.6, 47.5, 2.0]]]],
        }
    )
    assert multi["coordinates"] == [[[[8.5, 47.4], [8.6, 47.5]]]]


def test_to_2d_leaves_2d_geometry_alone():
    geometry = {"type": "Point", "coordinates": [8.5, 47.4]}
    assert to_2d(geometry) == geometry


def test_feature_name_prefers_the_specific_key():
    # Communes carry both `gemname` and a `kanton` string; picking the wrong one files
    # every commune in Zug under "ZG".
    assert feature_name({"gemname": "Baar", "kanton": "ZG"}) == "Baar"
    assert feature_name({"name": "Zug", "label": "Zug"}) == "Zug"
    assert feature_name({"flaeche": 23873.0}) is None
    assert feature_name({"gemname": "   "}) is None
    # `label` is last because it is not always a name: on the locality register it is the
    # postcode as an integer, and on the country layer it is "Schweiz 2".
    assert (
        feature_name({"langtext": "Oerlikon", "plz": 8050, "label": 8050}) == "Oerlikon"
    )
    assert (
        feature_name(
            {"bez": "Schweiz", "displayname": "Schweiz 2", "label": "Schweiz 2"}
        )
        == "Schweiz"
    )


def test_lake_and_commune_of_the_same_name_both_survive():
    # swissBOUNDARIES3D files the lake Greifensee in the *commune* layer as a
    # `kantonsgebiet`. Deduping on the name alone kept whichever identify returned
    # first - observed live, that was the lake, and the commune became unreachable.
    lake = {"gemname": "Greifensee", "objektart_lookup": "kantonsgebiet"}
    commune = {"gemname": "Greifensee", "objektart_lookup": "gemeindegebiet"}
    assert (feature_name(lake), lake["objektart_lookup"]) != (
        feature_name(commune),
        commune["objektart_lookup"],
    )
    assert _kind(lake["objektart_lookup"], "gemeinde") == "kantonsgebiet"
    assert _kind(commune["objektart_lookup"], "gemeinde") == "gemeinde"
    assert _kind(None, "kanton") == "kanton"  # cantons carry no objektart at all


def test_time_enabled_layers_are_pinned_to_the_newest_vintage():
    # Unpinned, identify returns every historical vintage of every feature: 7 communes in
    # a Zug-sized box came back as 1228 "features" whose areas summed to 24104 km2, more
    # than half of Switzerland. Nothing downstream can tell a vintage from a neighbour.
    api = Swisstopo.__new__(Swisstopo)
    api._layers_config = {
        "de": {
            "hist": {"timeEnabled": True, "timestamps": ["2024", "2026", "2025"]},
            "plain": {"timeEnabled": False, "timestamps": ["current"]},
        }
    }

    newest = lambda lid: asyncio.run(api._newest_timestamp(lid, "de"))  # noqa: E731

    # Newest, not first and not last as listed - the catalogue does not sort them.
    assert newest("hist") == "2026"
    # Non-historised layers must stay unpinned rather than be pinned to "current".
    assert newest("plain") is None
    assert newest("absent-from-catalogue") is None


def test_divisions_are_grouped_by_name_not_deduped_to_one():
    # A locality is one polygon per postcode and Zürich has 24. Keeping the first would
    # put an eighth of the city on the map and label it Zürich.
    api = Swisstopo.__new__(Swisstopo)
    spec = DivisionLayer("ortschaft", "ch.x")
    parts = [
        {"properties": {"langtext": "Zürich", "plz": 8001}, "geometry": None},
        {"properties": {"langtext": "Zürich", "plz": 8002}, "geometry": None},
        {"properties": {"langtext": "Adliswil", "plz": 8134}, "geometry": None},
    ]
    api.fetch_features = lambda *a, **kw: _returns(FetchResult(parts))  # type: ignore[method-assign]

    groups = asyncio.run(api.fetch_divisions(spec))
    assert [len(g) for g in groups] == [2, 1]


def test_only_filter_keeps_switzerland_and_drops_the_enclaves():
    # The country layer holds four territories. Two are enclaves - "Italia" is Campione
    # d'Italia at 2.6 km2, "Deutschland" is Büsingen at 7.6 km2 - so publishing them under
    # those names would resolve a query for Germany to a village-sized polygon.
    api = Swisstopo.__new__(Swisstopo)
    spec = DivisionLayer("land", "ch.y", only=("Schweiz",))
    api.fetch_features = lambda *a, **kw: _returns(  # type: ignore[method-assign]
        FetchResult(
            [
                {"properties": {"bez": n}}
                for n in ("Schweiz", "Italia", "Liechtenstein", "Deutschland")
            ]
        )
    )

    groups = asyncio.run(api.fetch_divisions(spec))
    assert [g[0]["properties"]["bez"] for g in groups] == ["Schweiz"]


async def _returns(value):
    return value


def test_s3_key_disambiguates_names_that_slug_alike():
    # _slug is lossy, and the loser of a collision keeps its key while the winner
    # overwrites its polygon: the right name on the map, the wrong place under it.
    taken: dict[str, str] = {}
    assert _s3_key(taken, "gemeinde", "Bévilard").endswith("/bevilard.geojson")
    assert _s3_key(taken, "gemeinde", "Bevilard") != _s3_key({}, "gemeinde", "Bévilard")
    # The same name asked for twice is the same division, not a collision.
    assert _s3_key(taken, "gemeinde", "Bévilard").endswith("/bevilard.geojson")


def test_slug_survives_swiss_place_names():
    assert _slug("Biel/Bienne") == "biel-bienne"
    assert _slug("Zürich") == "zuerich"
    assert _slug("Neuchâtel") == "neuchatel"
    assert _slug(None) == "unnamed"


# ------------------------------------------------------------------- rerank


def test_parse_distinguishes_empty_answer_from_failure():
    # "None of these fit" is a real verdict and must not be mistaken for a broken model:
    # the first serves an empty result, the second has to fall back to vector order.
    assert _parse("[]", 5) == []
    assert _parse("the datasets are unrelated", 5) is None


def test_parse_survives_a_model_that_answers_twice():
    # Observed live from ministral-3-14b on a no-match query: a bare array followed by the
    # same array in a fence. A greedy match spanned both and json-failed, so "nothing
    # fits" became "search is broken" and four irrelevant layers were served instead.
    assert _parse("[]\n```json\n[]\n```", 4) == []
    assert _parse("```json\n[2, 1]\n```", 4) == [1, 0]
    assert _parse("Reviewing candidates [1-4], I keep: [3]", 4) == [2]


def test_parse_converts_to_zero_based_and_drops_junk():
    assert _parse("[2, 1]", 5) == [1, 0]
    assert _parse("Here you go: [1, 99, -3, 2]", 5) == [0, 1]
    assert _parse("[1, 1, 2]", 5) == [0, 1]
    # bools are ints in Python; True must not select candidate 0.
    assert _parse("[true, 2]", 5) == [1]


# -------------------------------------------------------------------- index


@pytest.fixture(scope="module")
def tiny_index(tmp_path_factory) -> GeoIndex:
    directory = tmp_path_factory.mktemp("index")
    layers = [
        _layer("ch.a.wald", "Waldareal", "Flächen mit Waldbedeckung in der Schweiz."),
        _layer(
            "ch.b.flug", "SIL Anhörung", "Sachplan Infrastruktur Luftfahrt, Anhörung."
        ),
        _layer(
            "ch.c.solar",
            "Solarenergie Dächer",
            "Eignung von Dachflächen für Photovoltaik.",
        ),
        # No abstract: must stay findable via the title-embedding fallback.
        _layer("ch.d.nodesc", "Gletscher", ""),
    ]
    divisions = [
        {
            "name": "Zürich",
            "kind": "kanton",
            "canton": "ZH",
            "bbox": [8.3, 47.2, 8.8, 47.7],
            "layer_id": "ch.x",
            "s3_key": "layers/divisions/kanton/zuerich.geojson",
        },
        {
            "name": "Baar",
            "kind": "gemeinde",
            "canton": "ZG",
            "bbox": [8.4, 47.1, 8.6, 47.3],
            "layer_id": "ch.y",
            "s3_key": "layers/divisions/gemeinde/baar.geojson",
        },
    ]
    build(directory, layers, divisions, StubEmbedder())
    return GeoIndex(directory, StubEmbedder())


@pytest.fixture(scope="module")
def tiny_index_with_levels(tmp_path_factory) -> GeoIndex:
    directory = tmp_path_factory.mktemp("levels")
    # Insertion order is the hierarchy, coarsest first, exactly as build.py writes it.
    divisions = [
        {
            "name": "Zürich",
            "kind": kind,
            "canton": "ZH",
            "bbox": [8.3, 47.2, 8.8, 47.7],
            "layer_id": "ch.x",
            "s3_key": f"layers/divisions/{kind}/zuerich.geojson",
            "feature_count": 24 if kind == "ortschaft" else 1,
        }
        for kind in ("kanton", "bezirk", "gemeinde", "ortschaft")
    ]
    build(directory, [_layer("ch.a", "Waldareal", "Wald.")], divisions, StubEmbedder())
    return GeoIndex(directory, StubEmbedder())


def _layer(layer_id: str, title: str, description: str) -> dict:
    return {
        "layer_id": layer_id,
        "title": title,
        "description": description,
        "layer_type": "wmts",
        "topics": "api",
        "attribution": "swisstopo",
        "data_owner": "BAFU",
        "details_url": "",
        "queryable": True,
        "displayable": True,
    }


def test_score_sums_both_halves_not_just_one(tiny_index):
    # The bug this pins: when each index was searched only to a fixed depth, a layer
    # present in one result list but not the other was scored on that half alone. Title
    # weight is 0.6, so any partial sum is capped at 0.6 - a score above it proves both
    # halves contributed.
    hits = tiny_index.search_layers("Waldareal", limit=99)
    top = next(h for h in hits if h.row["layer_id"] == "ch.a.wald")
    assert top.score > 0.6


def test_layer_without_abstract_still_scores(tiny_index):
    # A zero description vector would park it below the floor for every query forever.
    hits = tiny_index.search_layers("Gletscher", limit=99)
    top = next(h for h in hits if h.row["layer_id"] == "ch.d.nodesc")
    assert top.score > 0.5


def test_confidence_flags_a_photo_finish():
    from .index import Hit

    row = {"layer_id": "x"}
    assert confidence([Hit(0.9, row), Hit(0.4, row)])["low_confidence"] is False
    assert confidence([Hit(0.9, row), Hit(0.895, row)])["low_confidence"] is True
    assert confidence([])["low_confidence"] is True


def test_divisions_resolve_across_spelling(tiny_index):
    hits = tiny_index.search_divisions("Zurich", limit=5)
    assert hits[0].row["name"] == "Zürich"


def test_division_lookup_is_exact_and_kind_aware(tiny_index):
    assert tiny_index.division_by_name("baar")["kind"] == "gemeinde"
    assert tiny_index.division_by_name("Baar", kind="kanton") is None


def test_identical_names_rank_coarsest_first(tiny_index_with_levels):
    # One name at four levels is one vector and one score, and FAISS does not order exact
    # ties. An agent that takes the top bbox at face value must get the canton, not a
    # postcode area - so the tie-break is rid, which build.py writes coarsest first.
    hits = tiny_index_with_levels.search_divisions("Zürich", limit=10)
    assert [h.row["kind"] for h in hits] == [
        "kanton",
        "bezirk",
        "gemeinde",
        "ortschaft",
    ]


def test_an_unqualified_name_resolves_to_the_coarsest_division(tiny_index_with_levels):
    # Zürich is a canton, a district, a commune and a locality. Unqualified, the largest
    # of them is the safe answer; a locality would put one postcode area on the map.
    assert tiny_index_with_levels.division_by_name("Zürich")["kind"] == "kanton"
    assert (
        tiny_index_with_levels.division_by_name("Zürich", kind="ortschaft")[
            "feature_count"
        ]
        == 24
    )


def test_reused_layer_vectors_are_checked_against_the_catalogue(tmp_path):
    # Reuse is what makes a divisions-only rebuild 2 minutes instead of 25, and a stale
    # vector is not an error downstream - it is a search that ranks the wrong layer first
    # and looks like it worked. The guard is the only thing standing between the two.
    embedder = StubEmbedder()
    layers = [
        _layer("ch.a.wald", "Waldareal", "Wald."),
        _layer("ch.b.flug", "SIL", "Luftfahrt."),
    ]
    divisions = [
        {
            "name": "Baar",
            "kind": "gemeinde",
            "canton": "ZG",
            "bbox": None,
            "layer_id": "ch.y",
            "s3_key": "k",
        }
    ]
    build(tmp_path, layers, divisions, embedder)

    # Same catalogue: reuse, and the reported dim still comes from the stored vectors.
    stats = build(
        tmp_path, layers, divisions + divisions, embedder, reuse_layer_vectors=True
    )
    assert stats == {"layers": 2, "divisions": 2, "dim": StubEmbedder.dim}

    renamed = [_layer("ch.a.wald", "Gletscher", "Wald."), layers[1]]
    with pytest.raises(ValueError, match="do not match the catalogue"):
        build(tmp_path, renamed, divisions, embedder, reuse_layer_vectors=True)

    with pytest.raises(ValueError, match="holds 2 vectors"):
        build(
            tmp_path,
            layers + [layers[0]],
            divisions,
            embedder,
            reuse_layer_vectors=True,
        )

    with pytest.raises(ValueError, match="does not exist"):
        build(tmp_path / "empty", layers, divisions, embedder, reuse_layer_vectors=True)


def test_index_refuses_a_model_it_was_not_built_with(tiny_index):
    # Cosine similarity between vectors from two different models is noise, and it looks
    # exactly like a working search.
    class OtherModel:
        model_name = "eu.cohere.embed-v4:0"

    with pytest.raises(ValueError, match="built with"):
        GeoIndex(tiny_index.directory, OtherModel())


def test_index_refuses_to_guess_the_model_it_was_built_with(tiny_index, tmp_path):
    # There used to be a fallback here: no meta.model row meant "assume the default".
    # That made the check above compare the default against itself and pass, so an index
    # of unknown provenance loaded clean and then ranked by vectors nothing could read.
    import shutil

    import duckdb

    shutil.copytree(tiny_index.directory, tmp_path / "copy")
    db = duckdb.connect(str(tmp_path / "copy" / "geosearch.duckdb"))
    db.execute("DELETE FROM meta WHERE key = 'model'")
    db.close()

    with pytest.raises(ValueError, match="no meta.model row"):
        GeoIndex(tmp_path / "copy", StubEmbedder())


def test_index_refuses_a_faiss_file_that_lost_rows(tiny_index, tmp_path):
    # rid is positional: row N in DuckDB is vector N in the .faiss file, coupled by
    # nothing but build.py walking the same list twice. A half-finished `aws s3 sync`
    # leaves a shorter index that still searches - and silently returns the wrong layer.
    import shutil

    import faiss

    shutil.copytree(tiny_index.directory, tmp_path / "short")
    index = faiss.read_index(str(tmp_path / "short" / "layer_title.faiss"))
    index.remove_ids(np.array([index.ntotal - 1], dtype=np.int64))
    faiss.write_index(index, str(tmp_path / "short" / "layer_title.faiss"))

    with pytest.raises(ValueError, match="vectors but"):
        GeoIndex(tmp_path / "short", StubEmbedder())


# ---------------------------------------------------------- boundaries and display


def test_boundary_store_reads_image_shipped_geojson(tmp_path):
    from .boundaries import BoundaryStore

    path = tmp_path / "layers" / "divisions" / "baar.geojson"
    path.parent.mkdir(parents=True)
    collection = {"type": "FeatureCollection", "features": []}
    path.write_text(json.dumps(collection), encoding="utf-8")

    store = BoundaryStore(tmp_path)

    assert store.get_geojson("layers/divisions/baar.geojson") == collection


class _ToolIndex:
    def division_by_name(self, name, kind=None):
        if name != "Baar" or kind not in (None, "gemeinde"):
            return None
        return {
            "name": "Baar",
            "kind": "gemeinde",
            "s3_key": "layers/divisions/baar.geojson",
            "feature_count": 1,
            "bbox": [8.4, 47.1, 8.6, 47.3],
        }


class _ToolSwisstopo:
    def __init__(self, *, complete=True):
        self.complete = complete

    async def fetch_features(self, *_args, **_kwargs):
        return FetchResult(
            [_square(8.45, 47.15, 8.55, 47.25, name="Baar")],
            complete=self.complete,
            limit_reason=None if self.complete else "feature_limit",
        )


class _ToolPublisher:
    def __init__(self):
        self.calls = []

    async def publish_layer(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return PublishedLayer(
            capability="A" * 43,
            url="https://tiles.test/tiles/" + "A" * 43 + "/{z}/{x}/{y}.mvt",
            dispose_url="/data/layers/" + "A" * 43,
            expires_at=datetime(2026, 8, 11, 12, 5, tzinfo=UTC),
            byte_count=1234,
            min_zoom=0,
            max_zoom=18,
        )


class _ToolBoundaries:
    def get_geojson(self, _key):
        return {
            "type": "FeatureCollection",
            "features": [_square(8.4, 47.1, 8.6, 47.3, name="Baar")],
        }


def _server_for_display_tests(*, complete=True):
    from .server import build_server

    publisher = _ToolPublisher()
    server = build_server(
        _ToolIndex(),
        _ToolSwisstopo(complete=complete),
        artifacts=publisher,
        store=_ToolBoundaries(),
    )
    return server, publisher


def _assert_mvt_layer(layer):
    assert layer["format"] == "mvt"
    assert layer["url"].startswith("https://tiles.test/tiles/")
    assert layer["url"].endswith("/{z}/{x}/{y}.mvt")
    assert "fallback_url" not in layer
    assert layer["dispose_url"].startswith("/data/layers/")
    assert layer["url_expires_at"].endswith("Z")
    assert layer["min_zoom"] == 0
    assert layer["max_zoom"] == 18
    assert not any("parquet" in str(value).lower() for value in layer.values())
    assert not {"source_url", "source_key", "canonical_url"} & layer.keys()


def test_display_division_returns_only_the_mvt_protocol_and_publishes_complete():
    async def exercise():
        server, publisher = _server_for_display_tests()
        result = await server.call_tool(
            "display_division", {"name": "Baar", "kind": "gemeinde"}
        )
        return result.structured_content["layer"], publisher

    layer, publisher = asyncio.run(exercise())
    _assert_mvt_layer(layer)
    assert publisher.calls[0][1] == {"complete": True}
    assert layer["id"] == "division-gemeinde-Baar"
    assert layer["name"] == "Baar"
    assert layer["geometry_type"] == "polygon"
    assert layer["feature_count"] == 1
    assert layer["bbox"] == [8.4, 47.1, 8.6, 47.3]
    assert layer["attribution"].endswith("swissBOUNDARIES3D")


def test_display_layer_returns_only_mvt_and_passes_cached_completeness():
    async def exercise():
        server, publisher = _server_for_display_tests(complete=False)
        filtered = await server.call_tool(
            "filter_features",
            {"layer_id": "ch.test", "bbox": [8.4, 47.1, 8.6, 47.3]},
        )
        result = await server.call_tool(
            "display_layer",
            {
                "result_id": filtered.structured_content["result_id"],
                "name": "Baar",
                "fill_color": "#4a7c59",
                "opacity": 0.7,
            },
        )
        return result.structured_content["layer"], publisher

    layer, publisher = asyncio.run(exercise())
    _assert_mvt_layer(layer)
    assert layer["truncated"] is True
    assert publisher.calls[0][1] == {"complete": False}
    assert layer["id"].startswith("fs_")
    assert layer["name"] == "Baar"
    assert layer["geometry_type"] == "polygon"
    assert layer["feature_count"] == 1
    assert layer["bbox"] == [8.45, 47.15, 8.55, 47.25]
    assert layer["attribution"] == "swisstopo / geo.admin.ch · ch.test"
    assert layer["style_hint"] == {"fill_color": "#4a7c59", "opacity": 0.7}


def test_layer_publisher_constructs_only_the_private_s3_client(monkeypatch):
    import boto3

    from .server import _layer_publisher

    calls = []

    def client(service, **kwargs):
        calls.append((service, kwargs))
        return object()

    monkeypatch.setattr(boto3, "client", client)
    monkeypatch.setenv("GEOSEARCH_S3_BUCKET", "layers")
    monkeypatch.setenv("GEOSEARCH_S3_REGION", "eu-central-1")
    monkeypatch.setenv("GEOSEARCH_S3_ENDPOINT", "http://s3.test")
    monkeypatch.setenv("GEOSEARCH_TILE_QUEUE_URL", "https://sqs.test/queue")

    _layer_publisher()

    assert calls == [
        (
            "s3",
            {
                "region_name": "eu-central-1",
                "endpoint_url": "http://s3.test",
                "aws_access_key_id": "local",
                "aws_secret_access_key": "local",
            },
        )
    ]


def _square(x0, y0, x1, y1, **props):
    ring = [[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]]
    return {
        "type": "Feature",
        "properties": props,
        "geometry": {"type": "Polygon", "coordinates": [ring]},
    }


def test_clip_cuts_to_the_boundary_and_drops_the_neighbours():
    from .geometry import clip, measure

    boundary = [_square(0, 0, 1, 1)]
    features = [
        _square(0.2, 0.2, 0.4, 0.4, name="inside"),
        _square(0.5, 0.5, 1.5, 1.5, name="straddles"),
        _square(2, 2, 3, 3, name="outside"),
        # Shares only the eastern edge: the intersection is a line, not an area. This is
        # every commune along a canton border, so it is the case that decides whether a
        # count means anything.
        _square(1, 0, 2, 1, name="touches"),
    ]
    kept = clip(features, boundary)

    assert [f["properties"]["name"] for f in kept] == ["inside", "straddles"]
    # Cut, not merely kept: the straddling square contributes a quarter of itself.
    assert (
        kept[1]["geometry"]["coordinates"][0]
        != features[1]["geometry"]["coordinates"][0]
    )
    assert measure(kept)["area_km2"] < measure(features[:2])["area_km2"]


def test_clip_keeps_points_that_fall_inside():
    from .geometry import clip

    boundary = [_square(0, 0, 1, 1)]
    points = [
        {
            "type": "Feature",
            "properties": {"name": "in"},
            "geometry": {"type": "Point", "coordinates": [0.5, 0.5]},
        },
        {
            "type": "Feature",
            "properties": {"name": "out"},
            "geometry": {"type": "Point", "coordinates": [5, 5]},
        },
    ]
    assert [f["properties"]["name"] for f in clip(points, boundary)] == ["in"]


def test_clip_drops_the_slivers_two_datasets_leave_at_their_shared_edge():
    from .geometry import clip

    # Measured live: clipping the commune layer to the locality of Wengen leaves 22 m² of
    # Grindelwald next to 34 km² of Lauterbrunnen, because the postcode register and
    # swissBOUNDARIES3D were surveyed apart. A count cannot tell that from a commune.
    boundary = [_square(0, 0, 1, 1)]
    features = [
        _square(0.5, 0.5, 1.5, 1.5, name="real overlap"),
        _square(0.999999, 0, 2, 1, name="misalignment"),
    ]
    assert [f["properties"]["name"] for f in clip(features, boundary)] == [
        "real overlap"
    ]


def test_mcp_answers_the_host_the_backend_dials_and_refuses_the_rest(monkeypatch):
    """The failure this exists for produced a 421 in the cluster and nothing locally.

    The SDK's DNS-rebinding guard allows loopback only. The container health check dials
    127.0.0.1 and stayed green, so the service looked healthy while every tool call the
    backend made - addressed to the service name - came back `421 Misdirected Request`.
    Asserting the middleware's verdict directly, because a request that never leaves the
    process is what the guard inspects.
    """
    from mcp.server.transport_security import TransportSecurityMiddleware

    from .server import _transport_security

    monkeypatch.setenv("GEOSEARCH_ALLOWED_HOSTS", "sgs-llm-geosearch:8790")
    guard = TransportSecurityMiddleware(_transport_security(8790))

    assert guard._validate_host("sgs-llm-geosearch:8790")
    assert guard._validate_host("127.0.0.1:8790"), (
        "the container health check must keep working"
    )
    assert not guard._validate_host("evil.example.com")

    # Unset is a workstation, where the guard is the only thing standing between a browser
    # and a local server - it must not fall open just because the deployment var is absent.
    monkeypatch.delenv("GEOSEARCH_ALLOWED_HOSTS")
    assert not TransportSecurityMiddleware(_transport_security(8790))._validate_host(
        "sgs-llm-geosearch:8790"
    )
