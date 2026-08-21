"""Agent-facing explanations shared by MCP instructions, resources, and a tool."""

from __future__ import annotations

from typing import Final

VALID_LANGUAGES: Final = ("de", "fr", "it", "rm", "en")
VALID_DIVISION_KINDS: Final = (
    "land",
    "kanton",
    "bezirk",
    "gemeinde",
    "kommunanz",
    "kantonsgebiet",
    "ortschaft",
)
VALID_GEOCODE_ORIGINS: Final = (
    "address",
    "parcel",
    "zipcode",
    "gazetteer",
    "gg25",
    "district",
    "kantone",
)

AGENT_INSTRUCTIONS = """Use this read-only server to discover official Swiss federal
geodata. Keep the subject and place separate: search_datasets receives the topic only,
while search_divisions resolves an area. When one request combines both, call
create_map_preview with the selected dataset IDs and chosen division bbox; dataset-search
links alone use the nationwide view. Present one labelled link for every returned
dataset_previews item; a combined link is optional and never replaces individual links.
Prefer a gemeinde for a city/town request unless the user asks for its district or locality.
Use geocode_location for an address, parcel,
postcode, or point. For identify_at_point, use the parcel, oereb, or all_relevant preset,
and/or pass exact dataset IDs chosen through dataset search and description. Coordinates
and bounding boxes are always WGS84 (EPSG:4326); geocoding additionally reports Swiss
LV95 (EPSG:2056). Open map_preview_url to inspect results in the official map viewer. A
division bbox is a map focus rectangle, not the exact boundary. Never invent a ch.*
dataset ID, division_ref, coordinate, or administrative relationship. Never construct or
edit a map.geo.admin.ch URL: copy the returned map_preview_url or map_feature_url verbatim.
The viewer's center and crosshair URL parameters require LV95, not WGS84."""

GUIDES: Final[dict[str, dict[str, object]]] = {
    "overview": {
        "title": "Swisstopo search workflow",
        "related_tools": [
            "search_datasets",
            "describe_dataset",
            "search_divisions",
            "create_map_preview",
            "geocode_location",
            "identify_at_point",
        ],
        "content": """This server is a read-only discovery connector for public
geo.admin.ch data. A reliable workflow is: (1) search_datasets with only the subject,
(2) search_divisions if the question names an area, (3) create_map_preview with selected
dataset IDs and the chosen division bbox for separate place-centred layer views, (4)
describe_dataset before using attributes or interpreting a layer, (5) geocode_location
for precise addresses or named points, and (6) identify_at_point to read feature records
from already-selected datasets.
For common cadastral questions, identify_at_point can resolve the parcel, oereb, or
all_relevant preset without a separate layer search. Every dataset and point result has
a ready-to-open official map_preview_url. The server does not download datasets, return
GeoJSON, clip boundaries, publish map layers, or perform spatial analysis.""",
    },
    "datasets": {
        "title": "Datasets and map layers",
        "related_tools": [
            "search_datasets",
            "describe_dataset",
            "create_map_preview",
            "identify_at_point",
        ],
        "content": """In geo.admin.ch, a searchable dataset is represented by a stable
layer identifier such as ch.swisstopo.swissboundaries3d-gemeinde-flaeche.fill. A result
may be displayable, queryable feature-by-feature, or both. queryable=false usually means
raster or image content; do not attempt feature lookup on it. search_datasets ranks a
packaged multilingual catalogue snapshot and merges current SearchServer matches when
the public API is available. describe_dataset retrieves current schema, timestamps,
owner, legend, details, and download links. Treat the returned data owner and metadata
links as authoritative and do not infer missing fields. Dataset search and description
map_preview_url values open a nationwide view. When a user names a place, pass selected
dataset IDs and the resolved bbox or point to create_map_preview, then present every
dataset_previews link separately. A combined preview is only an optional extra.""",
    },
    "divisions": {
        "title": "Swiss divisions and named areas",
        "related_tools": ["search_divisions", "create_map_preview"],
        "content": """The division index contains Switzerland (land), 26 cantons
(kanton), districts (bezirk), communes (gemeinde), shared territories (kommunanz),
special canton territories such as large lakes (kantonsgebiet), and localities/postcode
areas (ortschaft). A locality is below commune level and is why names such as Wengen,
Gstaad, Verbier, or Davos Platz can resolve even when they are not communes. One name can
occur at several levels, so preserve kind and division_ref. Prefer gemeinde for ordinary
city/town wording unless the user explicitly wants the district or locality. bbox is
WGS84 and encloses the area; it is not the exact polygon and must not be used to prove
that something lies inside the administrative boundary. Copy it to create_map_preview
when selected layers should open centred on that division.""",
    },
    "geocoding": {
        "title": "Geocoding precise Swiss locations",
        "related_tools": ["geocode_location", "identify_at_point"],
        "content": """Use geocode_location for a street address, cadastral parcel,
postcode, named point, district, or canton. Restrict origins when intent is known—for an
address use [\"address\"], for a parcel use [\"parcel\"]. Results are candidates from
the official SearchServer, not address certificates; prefer exact matches with official
related_features. Each result includes WGS84 longitude/latitude and LV95
easting/northing. location_ref is an identifier for citation, not hidden server state;
pass the returned numeric WGS84 coordinates to identify_at_point. Each candidate includes
a map_preview_url centered on the result. For parcel details use preset="parcel"; for
ÖREB/PLR availability and official cantonal extract links use preset="oereb"; use
preset="all_relevant" for both. Identify results are exploratory and omit geometry and
GeoJSON. An official cantonal ÖREB PDF/web extract is the authoritative follow-up.""",
    },
    "coordinates": {
        "title": "Coordinate reference systems",
        "related_tools": ["search_divisions", "geocode_location", "identify_at_point"],
        "content": """All bbox values are [west, south, east, north] in WGS84
(EPSG:4326). Point tools name longitude before latitude. Geocoding also returns LV95
(EPSG:2056) as easting and northing. Do not swap axes: some historical geo.admin.ch
responses use ambiguous x/y labels, which this server deliberately does not expose.
Never pass LV95 metre coordinates to identify_at_point, which accepts WGS84 only. In the
opposite direction, never put WGS84 longitude/latitude in a map viewer center or crosshair
parameter. Use the returned map URL verbatim because it already contains LV95.""",
    },
}


def guide(topic: str) -> dict[str, object] | None:
    """Return a copy so callers cannot mutate the shared guide catalogue."""
    entry = GUIDES.get(topic.strip().casefold())
    return dict(entry) if entry is not None else None
