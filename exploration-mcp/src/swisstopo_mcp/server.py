"""MCP tool, resource, and prompt definitions for standalone Swiss data discovery."""

from __future__ import annotations

import json
import re
from typing import Any, TypeGuard

from mcp.server import MCPServer
from mcp.types import ToolAnnotations
from pydantic import RootModel

from .catalog import CatalogIndex
from .geo_admin import GeoAdminClient, GeoAdminError
from .guides import (
    AGENT_INSTRUCTIONS,
    GUIDES,
    VALID_DIVISION_KINDS,
    VALID_GEOCODE_ORIGINS,
    VALID_LANGUAGES,
    guide,
)
from .links import (
    lv95_to_wgs84,
    map_viewer_url,
    wgs84_to_lv95,
    within_viewer_extent,
)
from .schemas import (
    DescribeDatasetOutput,
    GeocodeLocationOutput,
    IdentifyAtPointOutput,
    LV95Point,
    MapPreviewLinksOutput,
    PointInput,
    SearchDatasetsOutput,
    SearchDivisionsOutput,
    WGS84Point,
)

SERVER_NAME = "swisstopo-search"
SERVER_VERSION = "3.1.0"
_DATASET_ID = re.compile(r"^ch\.[A-Za-z0-9._-]+$")
_MAP_LINK_NOTE = (
    "Open every returned url, combined_link, map_preview_url, or map_feature_url verbatim. "
    "Never rebuild these links or put WGS84 longitude/latitude in the map viewer's center "
    "or crosshair parameters; those parameters require LV95 metre coordinates."
)
_DATASET_MAP_LINK_NOTE = (
    "Dataset search and description links use the nationwide view. When the user names "
    "a place, resolve it and call get_map_preview_links with the selected dataset IDs and "
    "the returned division bbox or geocoded point, then present every individual_links "
    "link separately. " + _MAP_LINK_NOTE
)

IDENTIFY_PRESETS: dict[str, dict[str, Any]] = {
    "parcel": {
        "dataset_ids": ("ch.swisstopo-vd.amtliche-vermessung",),
        "description": (
            "Cadastral parcel lookup with parcel number, EGRID, municipality/canton "
            "metadata, and available cantonal geoportal links."
        ),
    },
    "oereb": {
        "dataset_ids": ("ch.swisstopo-vd.stand-oerebkataster",),
        "description": (
            "ÖREB/PLR cadastre availability, responsible authority, parcel references, "
            "and official cantonal extract links when available."
        ),
    },
    "all_relevant": {
        "dataset_ids": (
            "ch.swisstopo-vd.amtliche-vermessung",
            "ch.swisstopo-vd.stand-oerebkataster",
        ),
        "description": "Combined cadastral parcel and ÖREB/PLR exploration lookup.",
    },
}

_LOCAL_READ = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=False,
)
_REMOTE_READ = ToolAnnotations(
    read_only_hint=True,
    destructive_hint=False,
    idempotent_hint=True,
    open_world_hint=True,
)


def _error(code: str, message: str, *, retryable: bool = False) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "retryable": retryable,
            "upstream_status": None,
        }
    }


def _output[OutputModel: RootModel[Any]](
    model: type[OutputModel], payload: dict[str, Any]
) -> OutputModel:
    """Validate a response while preserving its unwrapped JSON object on the wire."""
    return model.model_validate(payload)


def _point_coordinates(point: PointInput) -> tuple[float, float, float, float]:
    """Return longitude, latitude, easting, northing for either supported point CRS."""
    if isinstance(point, WGS84Point):
        longitude = point.longitude
        latitude = point.latitude
        easting, northing = wgs84_to_lv95(longitude, latitude)
    elif isinstance(point, LV95Point):
        longitude, latitude = lv95_to_wgs84(point.easting, point.northing)
        # Use the same forward projection and rounding path as map_viewer_url so the
        # returned centre is byte-for-byte consistent with the URL.
        easting, northing = wgs84_to_lv95(longitude, latitude)
    else:  # pragma: no cover - MCP input validation constructs one of the two models.
        raise TypeError("point must use EPSG:4326 or EPSG:2056")
    if not within_viewer_extent(easting, northing):
        raise ValueError("point must lie within the Swiss map extent")
    return longitude, latitude, easting, northing


def _language(value: str) -> str | None:
    normalized = value.strip().casefold()
    return normalized if normalized in VALID_LANGUAGES else None


def _valid_dataset_id(value: object) -> TypeGuard[str]:
    return isinstance(value, str) and _DATASET_ID.fullmatch(value) is not None


def _with_dataset_preview(dataset: dict[str, Any], language: str) -> dict[str, Any]:
    result = dict(dataset)
    dataset_id = result.get("dataset_id")
    if _valid_dataset_id(dataset_id):
        result["map_preview_url"] = map_viewer_url(
            language=language,
            dataset_ids=[dataset_id],
        )
        result["map_preview_scope"] = "switzerland"
    return result


def _with_location_preview(location: dict[str, Any], language: str) -> dict[str, Any]:
    result = dict(location)
    wgs84 = (result.get("coordinates") or {}).get("wgs84") or {}
    try:
        longitude = float(wgs84["longitude"])
        latitude = float(wgs84["latitude"])
    except (KeyError, TypeError, ValueError):
        return result
    result["map_preview_url"] = map_viewer_url(
        language=language,
        longitude=longitude,
        latitude=latitude,
    )
    return result


def _merge_dataset_results(
    offline: list[dict[str, Any]],
    live: list[dict[str, Any]],
    *,
    language: str,
    limit: int,
    queryable_only: bool,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    scores: dict[str, float] = {}
    for row in offline:
        dataset_id = row["dataset_id"]
        merged[dataset_id] = {**row, "sources": ["catalog_snapshot"]}
        scores[dataset_id] = 0.72 * float(row.get("relevance", 0.0))
    live_count = max(len(live), 1)
    for row in live:
        dataset_id = row["dataset_id"]
        live_score = 1.0 - (int(row.get("live_rank", live_count)) - 1) / live_count
        if dataset_id in merged:
            current = merged[dataset_id]
            for field in ("title", "summary", "queryable", "displayable", "layer_type"):
                if row.get(field) not in (None, ""):
                    current[field] = row[field]
            current["sources"].append("live_search")
            scores[dataset_id] += 0.38 * live_score
        else:
            merged[dataset_id] = {
                **{key: value for key, value in row.items() if key != "live_rank"},
                "language": language,
                "data_owner": None,
                "attribution": "swisstopo / geo.admin.ch",
                "details_url": None,
                "topics": [],
                "match_basis": "live_catalog",
                "matched_terms": [],
                "sources": ["live_search"],
            }
            scores[dataset_id] = 0.62 * live_score

    ranked = []
    for dataset_id, row in merged.items():
        if queryable_only and not row.get("queryable"):
            continue
        row.pop("relevance", None)
        row["relevance"] = round(scores[dataset_id], 4)
        ranked.append(row)
    ranked.sort(key=lambda row: (-float(row["relevance"]), row["dataset_id"]))
    if ranked and ranked[0]["relevance"]:
        maximum = float(ranked[0]["relevance"])
        for row in ranked:
            row["relevance"] = round(float(row["relevance"]) / maximum, 4)
    return ranked[:limit]


def build_server(
    catalog: CatalogIndex | None = None,
    api: GeoAdminClient | None = None,
) -> MCPServer:
    """Build a server with injectable data and HTTP services for deterministic tests."""
    index = catalog or CatalogIndex()
    geo_admin = api or GeoAdminClient()
    server = MCPServer(
        name=SERVER_NAME,
        title="Swisstopo Search",
        description=(
            "Read-only discovery of Swiss federal geodata datasets, named divisions, "
            "addresses, parcels, coordinates, and feature records."
        ),
        instructions=AGENT_INSTRUCTIONS,
        version=SERVER_VERSION,
        website_url="https://www.geo.admin.ch/",
    )

    @server.tool(
        title="Search Swiss datasets",
        annotations=_REMOTE_READ,
        structured_output=True,
    )
    async def search_datasets(
        query: str,
        language: str = "en",
        limit: int = 8,
        queryable_only: bool = False,
    ) -> SearchDatasetsOutput:
        """Find official Swiss federal datasets by subject.

        Pass only the subject, such as "avalanche hazards" or "solar potential"; resolve
        a place separately with search_divisions. Results use stable ch.* dataset IDs and
        say whether feature lookup is possible. Search combines a packaged multilingual
        snapshot with the current geo.admin.ch catalogue when reachable. If confidence is
        low, compare candidates instead of silently choosing the first.
        """
        clean_query = query.strip()
        if not clean_query:
            return _output(
                SearchDatasetsOutput,
                _error("invalid_query", "query must be a non-empty dataset subject."),
            )
        selected_language = _language(language)
        if selected_language is None:
            return _output(
                SearchDatasetsOutput,
                _error("invalid_language", f"language must be one of {list(VALID_LANGUAGES)}."),
            )
        if not 1 <= limit <= 20:
            return _output(
                SearchDatasetsOutput,
                _error("invalid_limit", "limit must be between 1 and 20."),
            )

        offline = index.search_datasets(
            clean_query,
            language=selected_language,
            limit=max(limit * 2, 12),
            queryable_only=queryable_only,
        )
        live: list[dict[str, Any]] = []
        live_status: dict[str, Any] = {"available": True}
        try:
            live = await geo_admin.search_datasets(
                clean_query,
                language=selected_language,
                limit=min(max(limit * 2, 12), 30),
            )
        except GeoAdminError as exc:
            live_status = {"available": False, "error": exc.as_dict()}

        datasets = _merge_dataset_results(
            offline,
            live,
            language=selected_language,
            limit=limit,
            queryable_only=queryable_only,
        )
        datasets = [_with_dataset_preview(dataset, selected_language) for dataset in datasets]
        margin = (
            round(float(datasets[0]["relevance"]) - float(datasets[1]["relevance"]), 4)
            if len(datasets) > 1
            else float(datasets[0]["relevance"])
            if datasets
            else None
        )
        result: dict[str, Any] = {
            "query": clean_query,
            "language": selected_language,
            "datasets": datasets,
            "result_count": len(datasets),
            "low_confidence": not datasets or (margin is not None and margin < 0.08),
            "score_margin": margin,
            "catalog_snapshot": index.dataset_metadata.get("generated_at"),
            "live_catalog": live_status,
            "map_link_note": _DATASET_MAP_LINK_NOTE,
            "note": None,
        }
        if not datasets:
            result["note"] = (
                "No matching official dataset was found. Try a broader subject term; "
                "do not add a place name to the dataset query."
            )
        return _output(SearchDatasetsOutput, result)

    @server.tool(
        title="Describe a Swiss dataset",
        annotations=_REMOTE_READ,
        structured_output=True,
    )
    async def describe_dataset(
        dataset_id: str,
        language: str = "en",
    ) -> DescribeDatasetOutput:
        """Return current metadata and schema for one official ch.* dataset ID.

        Use after search_datasets whenever field names, meaning, owner, timestamps,
        geometry type, legend, details, or downloads matter. Current geo.admin.ch
        metadata is preferred; the packaged snapshot is used if the public service is
        temporarily unavailable. Never guess an attribute that is absent from fields.
        """
        clean_id = dataset_id.strip()
        if not _valid_dataset_id(clean_id):
            return _output(
                DescribeDatasetOutput,
                _error(
                    "invalid_dataset_id",
                    "dataset_id must be an official ch.* identifier.",
                ),
            )
        selected_language = _language(language)
        if selected_language is None:
            return _output(
                DescribeDatasetOutput,
                _error("invalid_language", f"language must be one of {list(VALID_LANGUAGES)}."),
            )

        fallback = index.get_dataset(clean_id, selected_language)
        try:
            live = await geo_admin.describe_dataset(clean_id, language=selected_language)
        except GeoAdminError as exc:
            if fallback is None:
                return _output(DescribeDatasetOutput, {"error": exc.as_dict()})
            fallback.update(
                {
                    "source": "catalog_snapshot",
                    "snapshot_date": index.dataset_metadata.get("generated_at"),
                }
            )
            return _output(
                DescribeDatasetOutput,
                {
                    "dataset": _with_dataset_preview(fallback, selected_language),
                    "live_metadata": {"available": False, "error": exc.as_dict()},
                    "map_link_note": _DATASET_MAP_LINK_NOTE,
                },
            )
        if live is None:
            return _output(
                DescribeDatasetOutput,
                _error(
                    "unknown_dataset",
                    f"No official dataset named '{clean_id}' exists in the current catalogue.",
                ),
            )
        return _output(
            DescribeDatasetOutput,
            {
                "dataset": _with_dataset_preview(live, selected_language),
                "live_metadata": {"available": True},
                "map_link_note": _DATASET_MAP_LINK_NOTE,
            },
        )

    @server.tool(
        title="Search Swiss divisions",
        annotations=_LOCAL_READ,
        structured_output=True,
    )
    async def search_divisions(
        query: str,
        kinds: list[str] | None = None,
        canton: str | None = None,
        limit: int = 10,
    ) -> SearchDivisionsOutput:
        """Resolve a Swiss canton, district, commune, locality, or country area.

        Localities are below communes and include places such as Wengen and Verbier.
        Preserve each hit's kind and division_ref because names can occur at several
        levels. Optional kinds: land, kanton, bezirk, gemeinde, kommunanz,
        kantonsgebiet, ortschaft. bbox is WGS84 map focus only, not the exact boundary.
        """
        clean_query = query.strip()
        if not clean_query:
            return _output(
                SearchDivisionsOutput,
                _error("invalid_query", "query must be a non-empty Swiss place name."),
            )
        selected_kinds = [value.strip().casefold() for value in (kinds or [])]
        invalid = sorted(set(selected_kinds) - set(VALID_DIVISION_KINDS))
        if invalid:
            return _output(
                SearchDivisionsOutput,
                _error(
                    "invalid_division_kind",
                    f"Unsupported kinds {invalid}; use {list(VALID_DIVISION_KINDS)}.",
                ),
            )
        if canton and index.canton_code(canton) is None:
            return _output(
                SearchDivisionsOutput,
                _error(
                    "invalid_canton",
                    "canton must be a Swiss canton name or two-letter code.",
                ),
            )
        if not 1 <= limit <= 50:
            return _output(
                SearchDivisionsOutput,
                _error("invalid_limit", "limit must be between 1 and 50."),
            )
        divisions = index.search_divisions(
            clean_query,
            kinds=selected_kinds,
            canton=canton,
            limit=limit,
        )
        result: dict[str, Any] = {
            "query": clean_query,
            "divisions": divisions,
            "result_count": len(divisions),
            "snapshot_date": index.division_metadata.get("generated_at"),
            "bbox_note": "bbox is an enclosing WGS84 rectangle, not the exact division polygon.",
            "note": None,
        }
        if not divisions:
            result["note"] = f"No indexed Swiss division matches '{clean_query}'."
        return _output(SearchDivisionsOutput, result)

    @server.tool(
        title="Get GeoAdmin map preview links",
        annotations=_LOCAL_READ,
        structured_output=True,
    )
    async def get_map_preview_links(
        dataset_ids: list[str],
        focus_bbox: tuple[float, float, float, float] | None = None,
        point: PointInput | None = None,
        language: str = "en",
    ) -> MapPreviewLinksOutput:
        """Return separate place-centred GeoAdmin links for selected datasets.

        Use after search_datasets plus search_divisions when a request combines a subject
        and an area, such as "buildings in Olten". Copy the chosen division's complete
        WGS84 bbox into focus_bbox. For an address or exact point, instead copy either
        explicit coordinates object returned by geocode_location into point. Pass 1-10
        exact dataset IDs. Present every individual_links item as its own labelled link;
        combined_link is only an optional additional view. Use URLs verbatim.
        """
        requested_ids = [
            value.strip() if isinstance(value, str) else value for value in dataset_ids
        ]
        if not 1 <= len(requested_ids) <= 10 or any(
            not _valid_dataset_id(value) for value in requested_ids
        ):
            return _output(
                MapPreviewLinksOutput,
                _error(
                    "invalid_dataset_ids",
                    "dataset_ids must contain 1-10 official ch.* identifiers.",
                ),
            )
        resolved_ids = list(dict.fromkeys(requested_ids))
        selected_language = _language(language)
        if selected_language is None:
            return _output(
                MapPreviewLinksOutput,
                _error("invalid_language", f"language must be one of {list(VALID_LANGUAGES)}."),
            )

        has_bbox = focus_bbox is not None
        has_point = point is not None
        if has_bbox == has_point:
            return _output(
                MapPreviewLinksOutput,
                _error(
                    "invalid_map_focus",
                    "Provide exactly one focus: a WGS84 focus_bbox or an explicit point object.",
                ),
            )

        try:
            if point is not None:
                longitude, latitude, easting, northing = _point_coordinates(point)
                focus: dict[str, Any] = {
                    "type": "point",
                    "coordinate": point.model_dump(),
                }
                preview_scope = "point"
            else:
                assert focus_bbox is not None
                west, south, east, north = focus_bbox
                longitude = (west + east) / 2
                latitude = (south + north) / 2
                easting, northing = wgs84_to_lv95(longitude, latitude)
                focus = {
                    "type": "division_bbox",
                    "bbox": list(focus_bbox),
                    "crs": "EPSG:4326",
                }
                preview_scope = "division_bbox"

            individual_links = [
                {
                    "dataset_id": dataset_id,
                    "url": map_viewer_url(
                        language=selected_language,
                        dataset_ids=[dataset_id],
                        focus_bbox=focus_bbox,
                        longitude=longitude if point is not None else None,
                        latitude=latitude if point is not None else None,
                    ),
                }
                for dataset_id in resolved_ids
            ]
            combined_preview_url = (
                map_viewer_url(
                    language=selected_language,
                    dataset_ids=resolved_ids,
                    focus_bbox=focus_bbox,
                    longitude=longitude if point is not None else None,
                    latitude=latitude if point is not None else None,
                )
                if len(resolved_ids) > 1
                else None
            )
        except ValueError as exc:
            return _output(
                MapPreviewLinksOutput,
                _error("invalid_map_focus", str(exc)),
            )

        return _output(
            MapPreviewLinksOutput,
            {
                "dataset_ids": resolved_ids,
                "individual_links": individual_links,
                "combined_link": combined_preview_url,
                "focus": focus,
                "center": {
                    "easting": round(easting, 3),
                    "northing": round(northing, 3),
                    "crs": "EPSG:2056",
                },
                "map_preview_scope": preview_scope,
                "presentation_note": (
                    "Present one labelled link for every individual_links item. The combined "
                    "link is secondary and must not replace the individual links."
                ),
                "map_link_note": _MAP_LINK_NOTE,
            },
        )

    @server.tool(
        title="Geocode a Swiss location",
        annotations=_REMOTE_READ,
        structured_output=True,
    )
    async def geocode_location(
        query: str,
        origins: list[str] | None = None,
        language: str = "en",
        limit: int = 5,
    ) -> GeocodeLocationOutput:
        """Resolve a Swiss address, parcel, postcode, or named point precisely.

        Restrict origins when intent is known: address, parcel, zipcode, gazetteer, gg25,
        district, or kantone. Returns explicit WGS84 longitude/latitude and LV95
        easting/northing; never interpret historical x/y fields yourself. Results are
        official SearchServer candidates, so prefer exact matches and related features.
        """
        clean_query = query.strip()
        if not clean_query:
            return _output(
                GeocodeLocationOutput,
                _error("invalid_query", "query must be a non-empty location."),
            )
        selected_language = _language(language)
        if selected_language is None:
            return _output(
                GeocodeLocationOutput,
                _error("invalid_language", f"language must be one of {list(VALID_LANGUAGES)}."),
            )
        selected_origins = [value.strip().casefold() for value in (origins or [])]
        invalid = sorted(set(selected_origins) - set(VALID_GEOCODE_ORIGINS))
        if invalid:
            return _output(
                GeocodeLocationOutput,
                _error(
                    "invalid_origin",
                    f"Unsupported origins {invalid}; use {list(VALID_GEOCODE_ORIGINS)}.",
                ),
            )
        if not 1 <= limit <= 20:
            return _output(
                GeocodeLocationOutput,
                _error("invalid_limit", "limit must be between 1 and 20."),
            )
        try:
            locations = await geo_admin.geocode_location(
                clean_query,
                origins=selected_origins,
                language=selected_language,
                limit=limit,
            )
        except GeoAdminError as exc:
            return _output(GeocodeLocationOutput, {"error": exc.as_dict()})
        locations = [_with_location_preview(location, selected_language) for location in locations]
        return _output(
            GeocodeLocationOutput,
            {
                "query": clean_query,
                "language": selected_language,
                "locations": locations,
                "result_count": len(locations),
                "note": (
                    "Candidates come from the official SearchServer. Pass either returned "
                    "coordinates object—not location_ref—to identify_at_point."
                ),
                "map_link_note": _MAP_LINK_NOTE,
            },
        )

    @server.tool(
        title="Identify Swiss data at a point",
        annotations=_REMOTE_READ,
        structured_output=True,
    )
    async def identify_at_point(
        point: PointInput,
        dataset_ids: list[str] | None = None,
        preset: str | None = None,
        language: str = "en",
        limit: int = 20,
        year: int | None = None,
    ) -> IdentifyAtPointOutput:
        """Read complete feature attributes from selected datasets at an explicit point.

        Use preset parcel, oereb, or all_relevant for common cadastral exploration, and/or
        pass 1-10 exact dataset IDs chosen with search_datasets and describe_dataset. Copy
        either the WGS84 or LV95 coordinates object from geocode_location into point; the
        server converts it safely. Geometry and GeoJSON are omitted; attributes, official
        PDF/web links, and a ready-to-open map preview remain intact. Time-enabled datasets
        use their latest published timestamp by default. Before passing year for a
        historical view, call describe_dataset and choose one of its available_years.
        Raster datasets may not support feature lookup.
        """
        requested_ids = [
            value.strip() if isinstance(value, str) else value for value in (dataset_ids or [])
        ]
        if len(requested_ids) > 10 or any(not _valid_dataset_id(value) for value in requested_ids):
            return _output(
                IdentifyAtPointOutput,
                _error(
                    "invalid_dataset_ids",
                    "dataset_ids may contain at most 10 official ch.* identifiers.",
                ),
            )
        selected_preset = preset.strip().casefold() if isinstance(preset, str) else None
        if preset is not None and selected_preset not in IDENTIFY_PRESETS:
            return _output(
                IdentifyAtPointOutput,
                _error(
                    "invalid_preset",
                    f"preset must be one of {sorted(IDENTIFY_PRESETS)}.",
                ),
            )
        if not requested_ids and selected_preset is None:
            return _output(
                IdentifyAtPointOutput,
                _error(
                    "missing_identify_selection",
                    "Provide preset parcel, oereb, or all_relevant and/or exact dataset_ids.",
                ),
            )
        preset_entry = IDENTIFY_PRESETS.get(selected_preset or "")
        preset_ids = list(preset_entry["dataset_ids"]) if preset_entry else []
        resolved_ids = list(dict.fromkeys([*preset_ids, *requested_ids]))
        if len(resolved_ids) > 10:
            return _output(
                IdentifyAtPointOutput,
                _error(
                    "invalid_dataset_ids",
                    "The preset and dataset_ids resolve to more than 10 datasets.",
                ),
            )
        try:
            longitude, latitude, easting, northing = _point_coordinates(point)
        except ValueError as exc:
            return _output(
                IdentifyAtPointOutput,
                _error("invalid_coordinates", str(exc)),
            )
        selected_language = _language(language)
        if selected_language is None:
            return _output(
                IdentifyAtPointOutput,
                _error("invalid_language", f"language must be one of {list(VALID_LANGUAGES)}."),
            )
        if not 1 <= limit <= 200:
            return _output(
                IdentifyAtPointOutput,
                _error("invalid_limit", "limit must be between 1 and 200."),
            )
        if year is not None and not 1000 <= year <= 9999:
            return _output(
                IdentifyAtPointOutput,
                _error("invalid_year", "year must contain four digits."),
            )
        try:
            identify_result = await geo_admin.identify_at_point(
                resolved_ids,
                longitude,
                latitude,
                language=selected_language,
                limit=limit,
                year=year,
            )
        except GeoAdminError as exc:
            if exc.status_code == 400:
                return _output(
                    IdentifyAtPointOutput,
                    _error(
                        "dataset_not_queryable",
                        "At least one selected dataset cannot be queried feature-by-feature.",
                    ),
                )
            return _output(IdentifyAtPointOutput, {"error": exc.as_dict()})
        features = identify_result["features"]
        temporal_context = identify_result["temporal_context"]
        enriched_features: list[dict[str, Any]] = []
        for feature in features:
            enriched = dict(feature)
            feature_ref = enriched.get("feature_ref") or {}
            feature_dataset_id = feature_ref.get("dataset_id")
            feature_id = feature_ref.get("feature_id")
            if _valid_dataset_id(feature_dataset_id) and feature_id not in (None, ""):
                enriched["map_feature_url"] = map_viewer_url(
                    language=selected_language,
                    dataset_ids=[feature_dataset_id],
                    longitude=longitude,
                    latitude=latitude,
                    feature_id=str(feature_id),
                    year=year,
                )
            enriched_features.append(enriched)

        result: dict[str, Any] = {
            "point": {
                "wgs84": {
                    "longitude": longitude,
                    "latitude": latitude,
                    "crs": "EPSG:4326",
                },
                "lv95": {
                    "easting": round(easting, 3),
                    "northing": round(northing, 3),
                    "crs": "EPSG:2056",
                },
            },
            "selection": {
                "preset": selected_preset,
                "preset_description": preset_entry["description"] if preset_entry else None,
                "explicit_dataset_ids": requested_ids,
                "resolved_dataset_ids": resolved_ids,
            },
            "dataset_ids": resolved_ids,
            "temporal_context": temporal_context,
            "map_preview_url": map_viewer_url(
                language=selected_language,
                dataset_ids=resolved_ids,
                longitude=longitude,
                latitude=latitude,
                year=year,
            ),
            "feature_count": len(enriched_features),
            "features": enriched_features,
            "geometry_omitted": True,
            "map_link_note": _MAP_LINK_NOTE,
            "oereb_note": None,
        }
        if "ch.swisstopo-vd.stand-oerebkataster" in resolved_ids:
            result["oereb_note"] = (
                "This is an exploratory point lookup. For an authoritative ÖREB/PLR "
                "extract, open the official cantonal PDF or web URL returned in the "
                "feature properties/external_links."
            )
        return _output(IdentifyAtPointOutput, result)

    @server.resource(
        "swisstopo://guide/{topic}",
        name="swisstopo-guide",
        title="Swisstopo search guide",
        description="Guides: overview, datasets, divisions, geocoding, coordinates.",
        mime_type="text/markdown",
    )
    async def guide_resource(topic: str) -> str:
        entry = guide(topic)
        if entry is None:
            raise ValueError(f"Unknown guide '{topic}'. Available: {sorted(GUIDES)}")
        related_tools = entry.get("related_tools")
        if not isinstance(related_tools, list):
            raise ValueError(f"Guide '{topic}' has invalid related_tools metadata.")
        related = ", ".join(str(value) for value in related_tools)
        return f"# {entry['title']}\n\n{entry['content']}\n\nRelated tools: {related}\n"

    @server.resource(
        "swisstopo://catalog/stats",
        name="swisstopo-catalog-stats",
        title="Packaged catalogue statistics",
        description="Snapshot dates, counts, coordinate convention, and source datasets.",
        mime_type="application/json",
    )
    async def catalog_stats() -> str:
        return json.dumps(
            {
                **index.counts,
                "dataset_snapshot": index.dataset_metadata,
                "division_snapshot": index.division_metadata,
                "bbox_crs": "EPSG:4326",
                "attribution": "swisstopo / geo.admin.ch",
            },
            ensure_ascii=False,
        )

    @server.prompt(
        name="find_swiss_geodata",
        title="Find Swiss geodata",
        description="Start a careful dataset/place/geocoding discovery workflow.",
    )
    async def find_swiss_geodata(question: str, language: str = "en") -> str:
        return (
            f"Answer this question using the Swisstopo Search tools: {question}\n\n"
            f"Preferred response language: {language}. Separate the data subject from any "
            "place, preserve official IDs and coordinate labels, inspect metadata before "
            "using fields, and state uncertainty when search_datasets reports low confidence."
        )

    return server
