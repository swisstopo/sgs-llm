from __future__ import annotations

import pytest

from swisstopo_mcp.links import lv95_to_wgs84, map_viewer_url, wgs84_to_lv95


def test_dataset_preview_opens_layer_at_swiss_extent() -> None:
    url = map_viewer_url(
        language="en",
        dataset_ids=["ch.swisstopo-vd.amtliche-vermessung"],
    )

    assert url.startswith("https://map.geo.admin.ch/#/map?")
    assert "lang=en" in url
    assert "z=1" in url
    assert "layers=ch.swisstopo-vd.amtliche-vermessung" in url


def test_point_preview_converts_wgs84_to_lv95_and_enables_layers() -> None:
    url = map_viewer_url(
        language="de",
        dataset_ids=["ch.first.layer", "ch.second.layer"],
        longitude=7.451352119445801,
        latitude=46.92793655395508,
    )

    assert "center=2600968." in url
    assert ",1197426." in url
    assert "z=12" in url
    assert "layers=ch.first.layer;ch.second.layer" in url
    assert "crosshair=marker,2600968." in url


def test_regression_wgs84_values_are_never_written_to_center() -> None:
    url = map_viewer_url(language="en", longitude=7.9020, latitude=47.3400)

    assert "center=2635019.092,1243341.081" in url
    assert "center=7.902" not in url


def test_explicit_coordinate_conversions_preserve_axis_order() -> None:
    easting, northing = wgs84_to_lv95(7.451352, 46.927937)
    longitude, latitude = lv95_to_wgs84(easting, northing)

    assert easting == pytest.approx(2600968.69, abs=0.1)
    assert northing == pytest.approx(1197426.95, abs=0.1)
    assert longitude == pytest.approx(7.451352, abs=1e-7)
    assert latitude == pytest.approx(46.927937, abs=1e-7)


def test_division_bbox_preview_centers_layers_on_olten() -> None:
    url = map_viewer_url(
        language="en",
        dataset_ids=["ch.bfs.gebaeude_wohnungs_register"],
        focus_bbox=[7.874858, 47.311028, 7.929085, 47.368924],
    )

    assert "center=2635016.954,1243338.400" in url
    assert "z=6.689" in url
    assert "layers=ch.bfs.gebaeude_wohnungs_register" in url
    assert "crosshair=" not in url
    assert "swisssearch=" not in url


def test_point_outside_viewer_lv95_bounds_uses_coordinate_search() -> None:
    url = map_viewer_url(language="en", longitude=0.0, latitude=0.0)

    assert "center=" not in url
    assert "swisssearch=0.0,0.0" in url
    assert "swisssearch_autoselect=true" in url


def test_feature_preview_uses_map_viewer_feature_syntax() -> None:
    url = map_viewer_url(
        language="en",
        dataset_ids=["ch.test.layer"],
        longitude=7.0,
        latitude=46.0,
        feature_id="42",
    )

    assert "layers=ch.test.layer@features=42" in url
    assert "featureInfo=default" in url


def test_preview_requires_both_point_coordinates() -> None:
    with pytest.raises(ValueError, match="supplied together"):
        map_viewer_url(language="en", longitude=7.0)


def test_preview_rejects_invalid_or_conflicting_bbox_focus() -> None:
    with pytest.raises(ValueError, match="west, south, east, north"):
        map_viewer_url(language="en", focus_bbox=[8.0, 47.0, 7.0, 48.0])
    with pytest.raises(ValueError, match="either focus_bbox"):
        map_viewer_url(
            language="en",
            focus_bbox=[7.8, 47.2, 8.0, 47.4],
            longitude=7.9,
            latitude=47.3,
        )
