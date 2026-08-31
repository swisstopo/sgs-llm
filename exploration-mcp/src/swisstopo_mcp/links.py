"""Stable, agent-friendly links into the official geo.admin.ch map viewer."""

from __future__ import annotations

import math
from collections.abc import Iterable
from urllib.parse import urlencode

from pyproj import Transformer

MAP_VIEWER_URL = "https://map.geo.admin.ch/#/map"
DEFAULT_BACKGROUND = "ch.swisstopo.pixelkarte-farbe"

# Documented map-viewer bounds for an LV95 center.
_MIN_EASTING = 2_450_000
_MAX_EASTING = 2_900_000
_MIN_NORTHING = 1_050_000
_MAX_NORTHING = 1_350_000

_WGS84_TO_LV95 = Transformer.from_crs(4326, 2056, always_xy=True)
_LV95_TO_WGS84 = Transformer.from_crs(2056, 4326, always_xy=True)

# At z=1 the map viewer shows approximately the full Swiss extent. This value lets
# division bboxes choose a useful continuous zoom while leaving some visual padding.
_NATIONAL_VIEW_SPAN_METRES = 400_000
_BBOX_PADDING = 1.2


def wgs84_to_lv95(longitude: float, latitude: float) -> tuple[float, float]:
    """Convert a finite WGS84 point to explicitly ordered LV95 coordinates."""
    if not math.isfinite(longitude) or not math.isfinite(latitude):
        raise ValueError("longitude and latitude must be finite")
    if not (-180 <= longitude <= 180 and -90 <= latitude <= 90):
        raise ValueError("longitude and latitude must be valid WGS84 coordinates")
    return _WGS84_TO_LV95.transform(longitude, latitude)


def lv95_to_wgs84(easting: float, northing: float) -> tuple[float, float]:
    """Convert a finite Swiss LV95 point to explicitly ordered WGS84 coordinates."""
    if not math.isfinite(easting) or not math.isfinite(northing):
        raise ValueError("easting and northing must be finite")
    if not within_viewer_extent(easting, northing):
        raise ValueError("easting and northing must lie within the Swiss LV95 map extent")
    return _LV95_TO_WGS84.transform(easting, northing)


def within_viewer_extent(easting: float, northing: float) -> bool:
    """Return whether an LV95 point can be used as a GeoAdmin viewer centre."""
    return _MIN_EASTING <= easting <= _MAX_EASTING and _MIN_NORTHING <= northing <= _MAX_NORTHING


def _bbox_view(bbox: Iterable[float]) -> tuple[float, float, float]:
    """Return a WGS84 center and map-viewer zoom for a WGS84 bbox."""
    try:
        west, south, east, north = [float(value) for value in bbox]
    except (TypeError, ValueError) as exc:
        raise ValueError("focus_bbox must contain four numeric values") from exc

    values = (west, south, east, north)
    if not all(math.isfinite(value) for value in values):
        raise ValueError("focus_bbox values must be finite")
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError("focus_bbox must be [west, south, east, north] in valid WGS84 coordinates")

    longitude = (west + east) / 2
    latitude = (south + north) / 2
    projected_corners = [
        _WGS84_TO_LV95.transform(x, y)
        for x, y in ((west, south), (west, north), (east, south), (east, north))
    ]
    eastings = [point[0] for point in projected_corners]
    northings = [point[1] for point in projected_corners]
    span_metres = max(max(eastings) - min(eastings), max(northings) - min(northings))
    padded_span = max(span_metres * _BBOX_PADDING, 250)
    zoom = 1 + math.log2(_NATIONAL_VIEW_SPAN_METRES / padded_span)
    return longitude, latitude, min(max(zoom, 1), 12)


def map_viewer_url(
    *,
    language: str,
    dataset_ids: Iterable[str] = (),
    longitude: float | None = None,
    latitude: float | None = None,
    focus_bbox: Iterable[float] | None = None,
    feature_id: str | None = None,
    year: int | None = None,
) -> str:
    """Build a ready-to-open map.geo.admin.ch URL.

    Public MCP coordinates stay in WGS84, while the map viewer's ``center`` and
    ``crosshair`` URL parameters require LV95. ``focus_bbox`` is WGS84 and selects a
    centered, area-appropriate zoom without adding a point marker. A feature selection
    is only applied when exactly one layer is present.
    """
    layers = list(dict.fromkeys(value for value in dataset_ids if value))
    if (longitude is None) != (latitude is None):
        raise ValueError("longitude and latitude must be supplied together")
    if focus_bbox is not None and (longitude is not None or latitude is not None):
        raise ValueError("supply either focus_bbox or longitude/latitude, not both")
    if year is not None and not 1000 <= year <= 9999:
        raise ValueError("year must contain four digits")

    params: list[tuple[str, str]] = [("lang", language)]
    center_point: str | None = None
    point_marker = longitude is not None and latitude is not None
    if focus_bbox is not None:
        longitude, latitude, zoom = _bbox_view(focus_bbox)
        easting, northing = wgs84_to_lv95(longitude, latitude)
        if not within_viewer_extent(easting, northing):
            raise ValueError("focus_bbox center must lie within the Swiss map extent")
        center_point = f"{easting:.3f},{northing:.3f}"
        params.append(("center", center_point))
        params.append(("z", f"{zoom:.3f}".rstrip("0").rstrip(".")))
    elif longitude is not None and latitude is not None:
        easting, northing = wgs84_to_lv95(longitude, latitude)
        if within_viewer_extent(easting, northing):
            center_point = f"{easting:.3f},{northing:.3f}"
            params.append(("center", center_point))
        params.append(("z", "12"))
    else:
        params.append(("z", "1"))

    params.append(("topic", "ech"))
    if layers:
        layer_value = ";".join(layers)
        if feature_id and len(layers) == 1:
            layer_value = f"{layer_value}@features={feature_id}"
        params.append(("layers", layer_value))
    if year is not None:
        params.append(("timeSlider", str(year)))
    params.append(("bgLayer", DEFAULT_BACKGROUND))

    if center_point is not None and point_marker:
        params.append(("crosshair", f"marker,{center_point}"))
    elif point_marker:
        # The viewer accepts WGS84 coordinates through its search parameter, not center.
        params.extend(
            (
                ("swisssearch", f"{longitude},{latitude}"),
                ("swisssearch_autoselect", "true"),
            )
        )
    if feature_id and len(layers) == 1:
        params.append(("featureInfo", "default"))

    # These characters are part of documented map-viewer parameter syntax.
    query = urlencode(params, safe=",;:@=")
    return f"{MAP_VIEWER_URL}?{query}"
