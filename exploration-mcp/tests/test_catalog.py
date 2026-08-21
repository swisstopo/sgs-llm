from __future__ import annotations

from swisstopo_mcp.catalog import CatalogIndex


def test_snapshot_counts_are_complete() -> None:
    catalog = CatalogIndex()
    assert catalog.counts == {"datasets": 896, "divisions": 6272}


def test_exact_dataset_identifier_ranks_first() -> None:
    catalog = CatalogIndex()
    expected = "ch.bafu.hydroweb-warnkarte_national"

    results = catalog.search_datasets(expected, language="en", limit=3)

    assert results[0]["dataset_id"] == expected
    assert results[0]["match_basis"] == "exact_id"
    assert results[0]["relevance"] == 1.0


def test_multilingual_dataset_subjects_find_relevant_layers() -> None:
    catalog = CatalogIndex()

    english = catalog.search_datasets("avalanche hazards", language="en", limit=5)
    french = catalog.search_datasets("dangers de crues", language="fr", limit=5)

    assert "lawinen" in english[0]["dataset_id"]
    assert any("aquaprotect" in row["dataset_id"] for row in french)


def test_unrelated_dataset_query_returns_no_results() -> None:
    catalog = CatalogIndex()

    assert catalog.search_datasets("saffron risotto recipe", language="en") == []


def test_division_search_preserves_hierarchy_for_repeated_names() -> None:
    catalog = CatalogIndex()

    results = catalog.search_divisions("Bern", limit=3)

    assert [row["kind"] for row in results] == ["kanton", "gemeinde", "ortschaft"]
    assert all(row["bbox_crs"] == "EPSG:4326" for row in results)


def test_division_search_handles_accents_canton_aliases_and_localities() -> None:
    catalog = CatalogIndex()

    geneva = catalog.search_divisions("Geneve", kinds=["kanton"], limit=2)
    valais = catalog.search_divisions("Wallis", kinds=["kanton"], limit=2)
    wengen = catalog.search_divisions("Wengen", kinds=["ortschaft"], limit=2)

    assert geneva[0]["name"] == "Genève"
    assert valais[0]["name"] == "Valais"
    assert valais[0]["canton"] == "VS"
    assert wengen[0]["name"] == "Wengen"


def test_division_canton_filter_accepts_translated_name() -> None:
    catalog = CatalogIndex()

    results = catalog.search_divisions("Wengen", canton="Berne", limit=5)

    assert results[0]["canton"] == "BE"


def test_division_reference_is_stable_and_resolvable() -> None:
    catalog = CatalogIndex()
    selected = catalog.search_divisions("Switzerland", kinds=["land"], limit=1)[0]

    row = catalog.get_division(selected["division_ref"])

    assert row is not None
    assert row["name"] == "Schweiz"
    assert row["division_ref"] == "division:0"
