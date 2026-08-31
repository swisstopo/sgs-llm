"""Async wrappers around the public, unauthenticated geo.admin.ch APIs."""

from __future__ import annotations

import asyncio
import html
import logging
import re
from typing import Any
from urllib.parse import urljoin

import httpx
from pyproj import Transformer

from .catalog import CANTON_NAMES, normalize

logger = logging.getLogger(__name__)

API_ROOT = "https://api3.geo.admin.ch/rest/services"
SEARCH_URL = f"{API_ROOT}/ech/SearchServer"
LAYERS_CONFIG_URL = f"{API_ROOT}/all/MapServer/layersConfig"
LAYER_METADATA_URL = f"{API_ROOT}/api/MapServer"
MAPSERVER_URL = f"{API_ROOT}/ech/MapServer"
IDENTIFY_URL = f"{API_ROOT}/all/MapServer/identify"
ATTRIBUTION = "swisstopo / geo.admin.ch"

_TIMEOUT = httpx.Timeout(20.0, connect=10.0)
_TAGS = re.compile(r"<[^>]+>")
_MATCH_WORD = re.compile(r"\w+", re.UNICODE)
_TIMESTAMP_YEAR = re.compile(r"^(\d{4})")
_WGS84_TO_LV95 = Transformer.from_crs(4326, 2056, always_xy=True)


class GeoAdminError(RuntimeError):
    """An upstream failure with a stable agent-facing error code."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        status_code: int | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.retryable = retryable
        self.status_code = status_code
        self.details = details

    def as_dict(self) -> dict[str, Any]:
        error: dict[str, Any] = {
            "code": self.code,
            "message": str(self),
            "retryable": self.retryable,
            "upstream_status": self.status_code,
        }
        if self.details is not None:
            error["details"] = self.details
        return error


def strip_markup(value: object) -> str:
    return html.unescape(_TAGS.sub("", str(value or ""))).strip()


def _published_year(timestamp: str) -> int | None:
    """Return the human year encoded by a GeoAdmin timestamp, excluding sentinels."""
    match = _TIMESTAMP_YEAR.match(timestamp)
    if match is None:
        return None
    year = int(match.group(1))
    return None if year == 9999 else year


def _latest_timestamp(timestamps: list[str]) -> str | None:
    """Choose the newest published timestamp, including GeoAdmin's current sentinels."""
    if not timestamps:
        return None

    def sort_key(timestamp: str) -> tuple[bool, str]:
        is_current = timestamp.casefold() == "current" or timestamp.startswith("9999")
        return is_current, timestamp

    return max(timestamps, key=sort_key)


def _timestamp_for_year(timestamps: list[str], year: int) -> str | None:
    matching = [timestamp for timestamp in timestamps if _published_year(timestamp) == year]
    return _latest_timestamp(matching)


def _canton_code(value: str) -> str | None:
    normalized = normalize(value)
    for code, names in CANTON_NAMES.items():
        if normalized == normalize(code) or any(normalized == normalize(name) for name in names):
            return code
    return None


class GeoAdminClient:
    """One reusable HTTP client that always reads current GeoAdmin metadata."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._owns_client = client is None

    async def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=_TIMEOUT,
                headers={"User-Agent": "swisstopo-search-mcp/3.1.0 (+read-only discovery)"},
            )
        for attempt in range(2):
            try:
                response = await self._client.get(url, params=params)
                response.raise_for_status()
                payload = response.json()
                return payload if isinstance(payload, dict) else {}
            except httpx.HTTPStatusError as exc:
                status = exc.response.status_code
                if status < 500 or attempt == 1:
                    raise GeoAdminError(
                        "geo_admin_http_error",
                        f"geo.admin.ch returned HTTP {status}.",
                        retryable=status >= 500 or status == 429,
                        status_code=status,
                    ) from exc
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                if attempt == 1:
                    raise GeoAdminError(
                        "geo_admin_unavailable",
                        "The public geo.admin.ch service is temporarily unreachable.",
                        retryable=True,
                    ) from exc
            await asyncio.sleep(0)
        raise AssertionError("unreachable")

    async def aclose(self) -> None:
        if self._client is not None and self._owns_client:
            await self._client.aclose()
            self._client = None

    async def layers_config(self, language: str) -> dict[str, dict[str, Any]]:
        payload = await self._get(LAYERS_CONFIG_URL, {"lang": language})
        return {str(key): value for key, value in payload.items() if isinstance(value, dict)}

    async def layer_metadata(self, language: str) -> dict[str, dict[str, Any]]:
        payload = await self._get(LAYER_METADATA_URL, {"lang": language})
        return {
            row["layerBodId"]: row.get("attributes") or {}
            for row in payload.get("layers", [])
            if isinstance(row, dict) and isinstance(row.get("layerBodId"), str)
        }

    async def search_datasets(
        self,
        query: str,
        *,
        language: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        payload = await self._get(
            SEARCH_URL,
            {
                "searchText": query,
                "type": "layers",
                "lang": language,
                "limit": max(1, min(limit, 30)),
            },
        )
        config = await self.layers_config(language)
        results: list[dict[str, Any]] = []
        for rank, item in enumerate(payload.get("results", []), start=1):
            if not isinstance(item, dict):
                continue
            attrs = item.get("attrs") or {}
            dataset_id = attrs.get("layer")
            if not isinstance(dataset_id, str):
                continue
            capabilities = config.get(dataset_id, {})
            results.append(
                {
                    "dataset_id": dataset_id,
                    "title": strip_markup(attrs.get("label") or attrs.get("title")) or dataset_id,
                    "summary": strip_markup(attrs.get("detail"))[:600],
                    "queryable": bool(capabilities.get("tooltip")),
                    "displayable": capabilities.get("type")
                    in {"wmts", "wms", "geojson", "aggregate"},
                    "layer_type": capabilities.get("type"),
                    "live_rank": rank,
                }
            )
        return results

    async def describe_dataset(
        self,
        dataset_id: str,
        *,
        language: str,
    ) -> dict[str, Any] | None:
        config = (await self.layers_config(language)).get(dataset_id)
        if not isinstance(config, dict):
            return None
        metadata = (await self.layer_metadata(language)).get(dataset_id) or {}
        try:
            schema = await self._get(f"{MAPSERVER_URL}/{dataset_id}", {"lang": language})
        except GeoAdminError as exc:
            if exc.status_code == 400:
                schema = {}
            else:
                raise
        fields = []
        for field in schema.get("fields") or []:
            if not isinstance(field, dict) or not isinstance(field.get("name"), str):
                continue
            entry = {
                "name": field["name"],
                "alias": field.get("alias"),
                "type": field.get("type"),
            }
            if isinstance(field.get("values"), dict):
                entry["values"] = field["values"]
            fields.append(entry)
        timestamps = [str(value) for value in (config.get("timestamps") or [])]
        current_timestamp = _latest_timestamp(timestamps)
        available_years = sorted(
            {
                published_year
                for timestamp in timestamps
                if (published_year := _published_year(timestamp)) is not None
            }
        )
        return {
            "dataset_id": dataset_id,
            "title": strip_markup(config.get("label")) or dataset_id,
            "description": strip_markup(metadata.get("abstract")),
            "language": language,
            "owner": metadata.get("dataOwner"),
            "attribution": config.get("attribution") or ATTRIBUTION,
            "queryable": bool(config.get("tooltip")),
            "displayable": config.get("type") in {"wmts", "wms", "geojson", "aggregate"},
            "layer_type": config.get("type"),
            "geometry_type": schema.get("geometryType"),
            "fields": fields,
            "time_enabled": bool(config.get("timeEnabled")),
            "timestamps": timestamps,
            "available_years": available_years,
            "current_timestamp": current_timestamp,
            "latest_year": (
                _published_year(current_timestamp) if current_timestamp is not None else None
            ),
            "details_url": metadata.get("urlDetails"),
            "download_url": metadata.get("downloadUrl"),
            "legend_url": f"{MAPSERVER_URL}/{dataset_id}/legend?lang={language}",
            "data_status": metadata.get("dataStatus"),
            "source": "live_geo_admin",
        }

    async def geocode_location(
        self,
        query: str,
        *,
        origins: list[str] | None,
        language: str,
        limit: int,
    ) -> list[dict[str, Any]]:
        selected = list(origins or [])
        attempts: list[tuple[str, list[str]]] = []
        code = _canton_code(query)
        if code is not None and (not selected or "kantone" in selected):
            attempts.append((code, ["kantone"]))
        attempts.append((query, selected))

        seen: set[tuple[str, float, float]] = set()
        locations: list[dict[str, Any]] = []
        for search_text, search_origins in attempts:
            params: dict[str, Any] = {
                "searchText": search_text,
                "type": "locations",
                "lang": language,
                "limit": max(1, min(limit, 50)),
                "sr": 4326,
                "returnGeometry": "true",
                "geometryFormat": "geojson",
            }
            if search_origins:
                params["origins"] = ",".join(search_origins)
            payload = await self._get(SEARCH_URL, params)
            rows = payload.get("features") or payload.get("results") or []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                properties = row.get("properties") or row.get("attrs") or {}
                if not isinstance(properties, dict):
                    continue
                try:
                    longitude = float(properties["lon"])
                    latitude = float(properties["lat"])
                except (KeyError, TypeError, ValueError):
                    continue
                origin = str(properties.get("origin") or "location")
                key = (origin, round(longitude, 8), round(latitude, 8))
                if key in seen:
                    continue
                seen.add(key)
                easting, northing = _WGS84_TO_LV95.transform(longitude, latitude)
                related_features = []
                for link in properties.get("links") or []:
                    if not isinstance(link, dict) or not isinstance(link.get("href"), str):
                        continue
                    related_features.append(
                        {
                            "dataset_id": str(link.get("title") or ""),
                            "feature_id": link["href"].rstrip("/").rsplit("/", 1)[-1],
                            "url": urljoin("https://api3.geo.admin.ch", link["href"]),
                        }
                    )
                query_words = set(_MATCH_WORD.findall(query.casefold()))
                detail_words = set(
                    _MATCH_WORD.findall(str(properties.get("detail") or "").casefold())
                )
                feature_id = str(properties.get("featureId") or properties.get("id") or "")
                locations.append(
                    {
                        "location_ref": f"{origin}:{feature_id or len(locations)}",
                        "kind": origin,
                        "label": strip_markup(properties.get("label") or properties.get("detail")),
                        "coordinates": {
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
                        "match_quality": (
                            "exact" if query_words and query_words <= detail_words else "partial"
                        ),
                        "related_features": related_features,
                    }
                )
                if len(locations) >= limit:
                    return locations
            if locations:
                return locations[:limit]
        return locations[:limit]

    async def identify_at_point(
        self,
        dataset_ids: list[str],
        longitude: float,
        latitude: float,
        *,
        language: str,
        limit: int,
        year: int | None = None,
    ) -> dict[str, Any]:
        """Identify features at one point with deterministic temporal selection.

        Time-enabled layers are pinned to their newest published timestamp by default.
        An explicit year is resolved independently against every layer's published
        timestamps. Requests are grouped by effective timestamp because ``timeInstant``
        applies to the whole GeoAdmin identify request, not to individual layers.
        """
        config = await self.layers_config(language)
        temporal_datasets: list[dict[str, Any]] = []
        request_groups: dict[str | None, list[str]] = {}

        for dataset_id in dataset_ids:
            capabilities = config.get(dataset_id) or {}
            time_enabled = bool(capabilities.get("timeEnabled"))
            timestamp: str | None = None
            selection = "not_applicable"
            if time_enabled:
                timestamps = [str(value) for value in (capabilities.get("timestamps") or [])]
                if not timestamps:
                    raise GeoAdminError(
                        "temporal_metadata_unavailable",
                        f"Dataset {dataset_id} is time-enabled but publishes no timestamps.",
                        retryable=False,
                    )
                if year is None:
                    timestamp = _latest_timestamp(timestamps)
                    selection = "latest_published"
                else:
                    timestamp = _timestamp_for_year(timestamps, year)
                    selection = "explicit_year"
                    if timestamp is None:
                        available_years = sorted(
                            {
                                published_year
                                for value in timestamps
                                if (published_year := _published_year(value)) is not None
                            }
                        )
                        latest_timestamp = _latest_timestamp(timestamps)
                        availability = (
                            f" Published years span {available_years[0]}-{available_years[-1]} "
                            f"({len(available_years)} available)."
                            if available_years
                            else " No year-specific timestamps are published."
                        )
                        raise GeoAdminError(
                            "time_not_available",
                            (
                                f"Year {year} is not available for dataset {dataset_id}."
                                f"{availability} Call describe_dataset and use available_years."
                            ),
                            retryable=False,
                            details={
                                "dataset_id": dataset_id,
                                "requested_year": year,
                                "available_years": available_years,
                                "latest_timestamp": latest_timestamp,
                                "latest_year": (
                                    _published_year(latest_timestamp)
                                    if latest_timestamp is not None
                                    else None
                                ),
                            },
                        )

            temporal_datasets.append(
                {
                    "dataset_id": dataset_id,
                    "time_enabled": time_enabled,
                    "timestamp_used": timestamp,
                    "year_used": _published_year(timestamp) if timestamp is not None else None,
                    "selection": selection,
                }
            )
            request_groups.setdefault(timestamp, []).append(dataset_id)

        bounded_limit = max(1, min(limit, 200))
        features: list[dict[str, Any]] = []
        for timestamp, grouped_dataset_ids in request_groups.items():
            params: dict[str, Any] = {
                "geometry": f"{longitude},{latitude}",
                "geometryType": "esriGeometryPoint",
                "layers": "all:" + ",".join(grouped_dataset_ids),
                "tolerance": 0,
                "sr": 4326,
                "geometryFormat": "geojson",
                "returnGeometry": "false",
                "lang": language,
                "limit": bounded_limit,
            }
            if timestamp is not None:
                params["timeInstant"] = timestamp
            payload = await self._get(IDENTIFY_URL, params)
            for row in payload.get("results") or []:
                if not isinstance(row, dict) or row.get("featureId") == -99 or row.get("id") == -99:
                    continue
                properties = row.get("properties") or row.get("attributes") or {}
                if not isinstance(properties, dict):
                    properties = {}
                links = []
                for field, value in properties.items():
                    if not isinstance(value, str) or not value.lower().startswith(
                        ("http://", "https://")
                    ):
                        continue
                    path = value.lower().split("?", 1)[0]
                    links.append(
                        {
                            "field": str(field),
                            "kind": (
                                "pdf"
                                if path.endswith(".pdf") or "pdf" in str(field).casefold()
                                else "web"
                            ),
                            "url": value,
                        }
                    )
                features.append(
                    {
                        "feature_ref": {
                            "dataset_id": row.get("layerBodId"),
                            "feature_id": str(row.get("featureId", row.get("id"))),
                        },
                        "dataset_title": row.get("layerName"),
                        "properties": properties,
                        "external_links": links,
                    }
                )

        dataset_order = {dataset_id: index for index, dataset_id in enumerate(dataset_ids)}
        features.sort(
            key=lambda feature: dataset_order.get(
                str((feature.get("feature_ref") or {}).get("dataset_id")), len(dataset_order)
            )
        )
        temporal_context = {
            "requested_year": year,
            "mode": "explicit_year" if year is not None else "latest_by_dataset",
            "datasets": temporal_datasets,
            "note": (
                f"Time-enabled datasets were queried at their published {year} timestamp."
                if year is not None
                else "Each time-enabled dataset was queried at its latest published timestamp."
            ),
        }
        return {
            "features": features[:bounded_limit],
            "temporal_context": temporal_context,
        }
