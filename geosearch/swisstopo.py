"""Production geo.admin.ch connector.

Ported from swisstopo_project/swisstopo.py. The part worth porting is
`fetch_features`: identify caps a single response at 200 features, so one call over a
canton silently truncates. Subdividing the bbox into a grid and paginating each cell
lifts that cap. The original ran the cells on a ThreadPoolExecutor because it was
sync; here they are asyncio tasks behind a semaphore, so we stay on one event loop and
never open 64 sockets to geo.admin.ch at once.

Response shapes verified against the live API 2026-08-07.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin

import httpx
from pyproj import Transformer

logger = logging.getLogger(__name__)

API3 = "https://api3.geo.admin.ch/rest/services"
LAYERS_CONFIG = f"{API3}/all/MapServer/layersConfig"

# Every layer with its metadata in one 2.6 MB document, `abstract` included. This is
# what makes a description embedding possible at all - SearchServer only returns
# abstracts for layers it already decided to match, which is the problem we are fixing.
LAYER_METADATA = f"{API3}/api/MapServer"

IDENTIFY = f"{API3}/all/MapServer/identify"
SEARCH = f"{API3}/ech/SearchServer"
ECH_MAPSERVER = f"{API3}/ech/MapServer"
ATTRIBUTION_FALLBACK = "swisstopo / geo.admin.ch"

_WGS84_TO_LV95 = Transformer.from_crs(4326, 2056, always_xy=True)

# identify's own maximum per request. Not a total: pagination walks past it.
PAGE = 200

# Stops a runaway pagination loop if the API ever ignores `offset` and keeps serving
# page 1. 40 pages x 200 = 8000 features from a single grid cell, far past any real layer.
MAX_PAGES = 40

# Concurrent identify requests. 64 grid cells at once gets us rate-limited; 8 keeps a
# national commune fetch under a minute without upsetting anyone.
CONCURRENCY = 8

CH_BBOX = (5.9, 45.8, 10.6, 47.9)

_TAGS = re.compile(r"<[^>]+>")
_MATCH_WORD = re.compile(r"\w+", re.UNICODE)
_TIMEOUT = httpx.Timeout(60.0, connect=10.0)

# Candidate name properties, most specific first. Each division layer names its label
# column differently (`gemname` for communes, `name` for cantons, `langtext` for
# localities, `bez` for countries). `label` stays last because it is not always a name:
# on the locality register it holds the postcode as an integer, and on the country layer
# it is "Schweiz 2" rather than "Schweiz".
_NAME_KEYS = ("gemname", "bezname", "langtext", "bez", "name", "label", "gemeinde", "kanton")


@dataclass(frozen=True)
class DivisionLayer:
    kind: str
    layer_id: str
    # Names to keep, when the layer carries more than the level it is named for.
    only: tuple[str, ...] = ()


# The administrative hierarchy, coarsest first. All are `tooltip: true` in layersConfig,
# so all are identify-queryable.
DIVISIONS = (
    # The country layer holds four territories, not one: Schweiz plus the three foreign
    # bodies that touch it in this dataset. Two of those are the enclaves - "Italia" is
    # Campione d'Italia at 2.6 km2 and "Deutschland" is Buesingen at 7.6 km2 - so
    # publishing them under those names would resolve "Deutschland" to a village-sized
    # polygon. Liechtenstein is genuinely the whole principality, but it is not
    # Switzerland and its 11 municipalities are already in the commune layer.
    DivisionLayer("land", "ch.swisstopo.swissboundaries3d-land-flaeche.fill", only=("Schweiz",)),
    DivisionLayer("kanton", "ch.swisstopo.swissboundaries3d-kanton-flaeche.fill"),
    DivisionLayer("bezirk", "ch.swisstopo.swissboundaries3d-bezirk-flaeche.fill"),
    DivisionLayer("gemeinde", "ch.swisstopo.swissboundaries3d-gemeinde-flaeche.fill"),
    # The official locality register, below commune level: 4073 postcode areas over 3974
    # names, 2302 of which are not the name of any commune. It is what makes "Wengen",
    # "Gstaad", "Verbier" and "Davos Platz" resolvable at all.
    DivisionLayer("ortschaft", "ch.swisstopo-vd.ortschaftenverzeichnis_plz"),
)


class LayerNotQueryable(Exception):
    """The dataset exists but has no queryable feature table.

    identify answers HTTP 400 for raster layers. That is a fact about the dataset, not
    a transport failure, and the agent has to hear it as one - told merely that the
    tool failed, models retry the same layer until they run out of iterations.
    """

    def __init__(self, layer_id: str) -> None:
        super().__init__(layer_id)
        self.layer_id = layer_id


def strip_markup(text: Any) -> str:
    """SearchServer wraps matched substrings in <b> for highlighting."""
    return _TAGS.sub("", str(text or "")).strip()


def feature_name(properties: dict[str, Any]) -> str | None:
    for key in _NAME_KEYS:
        value = properties.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def to_2d(geometry: dict[str, Any]) -> dict[str, Any]:
    """Drops Z from any GeoJSON geometry.

    swissBOUNDARIES3D is, as the name promises, 3D. OpenLayers reads the third ordinate
    as part of the coordinate and the frontend hands everything to it as EPSG:4326, so
    a stray Z makes reprojection produce nonsense rather than fail loudly.
    """

    def strip(coords: Any) -> Any:
        if not isinstance(coords, list) or not coords:
            return coords
        if isinstance(coords[0], (int, float)):
            return coords[:2]
        return [strip(c) for c in coords]

    if "coordinates" in geometry:
        return {**geometry, "coordinates": strip(geometry["coordinates"])}
    if geometry.get("type") == "GeometryCollection":
        return {**geometry, "geometries": [to_2d(g) for g in geometry.get("geometries", [])]}
    return geometry


class Swisstopo:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._owned = client is None
        self._layers_config: dict[str, dict[str, Any]] = {}
        self._metadata: dict[str, dict[str, Any]] = {}
        self._semaphore = asyncio.Semaphore(CONCURRENCY)

    async def _get(self, url: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=_TIMEOUT)
        response = await self._client.get(url, params=params)
        response.raise_for_status()
        payload = response.json()
        return payload if isinstance(payload, dict) else {}

    async def aclose(self) -> None:
        if self._client is not None and self._owned:
            await self._client.aclose()
            self._client = None

    async def __aenter__(self) -> Swisstopo:
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    # ---------------------------------------------------------------- catalogue

    async def layers_config(self, lang: str = "de") -> dict[str, dict[str, Any]]:
        if not self._layers_config.get(lang):
            self._layers_config[lang] = await self._get(LAYERS_CONFIG, {"lang": lang})
        return self._layers_config[lang]

    async def search_catalog_layers(
        self, query: str, lang: str = "de", limit: int = 30
    ) -> list[dict[str, str]]:
        """Use SearchServer's language-specific lexical catalogue index.

        The local semantic index is intentionally built once in one language. This live
        source complements it for catalogue terms whose cross-language embedding is weak.
        """
        payload = await self._get(
            SEARCH,
            {"searchText": query, "type": "layers", "lang": lang, "limit": limit},
        )
        found: list[dict[str, str]] = []
        for item in payload.get("results", []):
            attrs = item.get("attrs") or {}
            layer_id = attrs.get("layer")
            if not layer_id:
                continue
            found.append(
                {
                    "layer_id": str(layer_id),
                    "title": strip_markup(attrs.get("label") or attrs.get("title")),
                    "description": str(attrs.get("detail") or ""),
                }
            )
        return found

    async def layer_metadata(self, lang: str = "de") -> dict[str, dict[str, Any]]:
        """layerBodId -> attributes, including the `abstract` we embed."""
        if not self._metadata.get(lang):
            payload = await self._get(LAYER_METADATA, {"lang": lang})
            self._metadata[lang] = {
                layer["layerBodId"]: layer.get("attributes") or {}
                for layer in payload.get("layers", [])
                if isinstance(layer.get("layerBodId"), str)
            }
        return self._metadata[lang]

    async def catalog(self, lang: str = "de") -> list[dict[str, Any]]:
        """Every catalogue layer as one flat record, ready to embed.

        layersConfig (896 entries) is the spine because it alone says whether a layer is
        queryable and how it renders; the metadata document (877) supplies the abstract.
        Layers missing from the metadata keep an empty description rather than being
        dropped - they are still displayable, and the title embedding can still find them.
        """
        config = await self.layers_config(lang)
        metadata = await self.layer_metadata(lang)
        records = []
        for layer_id, entry in config.items():
            if not isinstance(entry, dict):
                continue
            attrs = metadata.get(layer_id, {})
            records.append(
                {
                    "layer_id": layer_id,
                    "lang": lang,
                    "title": strip_markup(entry.get("label")) or layer_id,
                    "description": strip_markup(attrs.get("abstract")),
                    "layer_type": str(entry.get("type") or ""),
                    "topics": str(entry.get("topics") or ""),
                    "attribution": str(entry.get("attribution") or ""),
                    "data_owner": str(attrs.get("dataOwner") or ""),
                    "details_url": str(attrs.get("urlDetails") or ""),
                    # layersConfig carries no `queryable` field at all; identify support
                    # is exposed as `tooltip` (520 of 896). Verified live 2026-08-07.
                    "queryable": bool(entry.get("tooltip")),
                    "displayable": entry.get("type") in ("wmts", "wms", "geojson"),
                    "time_enabled": bool(entry.get("timeEnabled")),
                    "timestamps": [str(t) for t in (entry.get("timestamps") or [])],
                }
            )
        return records

    async def geocode_location(
        self,
        query: str,
        *,
        origins: list[str] | None = None,
        lang: str = "de",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Resolve an address, parcel, postcode, or named point.

        SearchServer's historical ``x``/``y`` names are deliberately not exposed: their
        meaning depends on the requested projection and has caused axis swaps in real
        integrations.  WGS84 longitude/latitude is taken from the explicit response
        fields and LV95 is derived with an always-XY transformer.
        """
        allowed = {
            "zipcode",
            "gg25",
            "district",
            "kantone",
            "gazetteer",
            "address",
            "parcel",
        }
        selected = [value for value in (origins or []) if value in allowed]
        params: dict[str, Any] = {
            "searchText": query,
            "type": "locations",
            "lang": lang,
            "limit": max(1, min(int(limit), 50)),
            "sr": 4326,
            "returnGeometry": "true",
            "geometryFormat": "geojson",
        }
        if selected:
            params["origins"] = ",".join(selected)
        payload = await self._get(SEARCH, params)

        rows = payload.get("features") or payload.get("results") or []
        locations: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            props = row.get("properties") or row.get("attrs") or {}
            if not isinstance(props, dict):
                continue
            try:
                longitude = float(props["lon"])
                latitude = float(props["lat"])
            except (KeyError, TypeError, ValueError):
                continue
            easting, northing = _WGS84_TO_LV95.transform(longitude, latitude)
            related = []
            for link in props.get("links") or []:
                if not isinstance(link, dict) or not isinstance(link.get("href"), str):
                    continue
                related.append(
                    {
                        "layer_id": str(link.get("title") or ""),
                        "feature_id": str(link["href"]).rstrip("/").rsplit("/", 1)[-1],
                        "url": urljoin("https://api3.geo.admin.ch", link["href"]),
                    }
                )
            origin = str(props.get("origin") or "location")
            feature_id = str(props.get("featureId") or props.get("id") or "")
            query_words = set(_MATCH_WORD.findall(query.casefold()))
            detail_words = set(
                _MATCH_WORD.findall(str(props.get("detail") or "").casefold())
            )
            locations.append(
                {
                    "location_ref": f"{origin}:{feature_id or len(locations)}",
                    "kind": origin,
                    "label": strip_markup(props.get("label") or props.get("detail")),
                    "coordinates": {
                        "wgs84": {"longitude": longitude, "latitude": latitude},
                        "lv95": {"easting": easting, "northing": northing},
                    },
                    # SearchServer explicitly says its numeric weight is not a stable
                    # confidence score.  Expose an interpretable match class instead.
                    "match_quality": (
                        "exact" if query_words and query_words <= detail_words
                        else "partial"
                    ),
                    "related_features": related,
                }
            )
        return locations

    async def describe_layer(self, layer_id: str, lang: str = "de") -> dict[str, Any] | None:
        """Merge catalogue, renderer, schema, time, and download metadata for one layer."""
        config = (await self.layers_config(lang)).get(layer_id)
        if not isinstance(config, dict):
            return None
        metadata = (await self.layer_metadata(lang)).get(layer_id) or {}
        schema = await self._get(f"{ECH_MAPSERVER}/{layer_id}", {"lang": lang})
        fields = []
        for field in schema.get("fields") or []:
            if not isinstance(field, dict) or not isinstance(field.get("name"), str):
                continue
            fields.append(
                {
                    "name": field["name"],
                    "alias": field.get("alias"),
                    "type": field.get("type"),
                }
            )
        timestamps = [str(value) for value in (config.get("timestamps") or [])]
        return {
            "layer_id": layer_id,
            "title": strip_markup(config.get("label")) or layer_id,
            "description": strip_markup(metadata.get("abstract")),
            "owner": metadata.get("dataOwner"),
            "attribution": config.get("attribution") or ATTRIBUTION_FALLBACK,
            "queryable": bool(config.get("tooltip")),
            "displayable": config.get("type") in ("wmts", "wms", "geojson"),
            "layer_type": config.get("type"),
            "geometry_type": schema.get("geometryType"),
            "fields": fields,
            "time_enabled": bool(config.get("timeEnabled")),
            "timestamps": timestamps,
            "current_timestamp": max(timestamps) if timestamps else None,
            "details_url": metadata.get("urlDetails"),
            "download_url": metadata.get("downloadUrl"),
            "legend_url": f"{ECH_MAPSERVER}/{layer_id}/legend?lang={lang}",
            "data_status": metadata.get("dataStatus"),
        }

    async def identify_at_point(
        self,
        layer_ids: list[str],
        longitude: float,
        latitude: float,
        *,
        lang: str = "de",
        return_geometry: bool = False,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Return complete structured feature records intersecting one WGS84 point."""
        selected = [layer_id for layer_id in layer_ids if isinstance(layer_id, str)][:10]
        if not selected:
            return []
        payload = await self._get(
            IDENTIFY,
            {
                "geometry": f"{float(longitude)},{float(latitude)}",
                "geometryType": "esriGeometryPoint",
                "layers": "all:" + ",".join(selected),
                "tolerance": 0,
                "sr": 4326,
                "geometryFormat": "geojson",
                "returnGeometry": str(bool(return_geometry)).lower(),
                "lang": lang,
                "limit": max(1, min(int(limit), 200)),
            },
        )
        features: list[dict[str, Any]] = []
        for row in payload.get("results") or []:
            if not isinstance(row, dict) or row.get("featureId") == -99 or row.get("id") == -99:
                continue
            properties = row.get("properties") or row.get("attributes") or {}
            if not isinstance(properties, dict):
                properties = {}
            external_links = []
            for key, value in properties.items():
                if not isinstance(value, str) or not value.lower().startswith(("http://", "https://")):
                    continue
                lowered = value.lower().split("?", 1)[0]
                external_links.append(
                    {
                        "field": str(key),
                        "kind": (
                            "pdf"
                            if lowered.endswith(".pdf") or "pdf" in str(key).casefold()
                            else "web"
                        ),
                        "label": str(key).replace("_", " "),
                        "url": value,
                    }
                )
            feature_id = row.get("featureId", row.get("id"))
            feature: dict[str, Any] = {
                "feature_ref": {
                    "layer_id": row.get("layerBodId"),
                    "feature_id": str(feature_id),
                },
                "layer_name": row.get("layerName"),
                "properties": properties,
                "external_links": external_links,
            }
            if return_geometry and isinstance(row.get("geometry"), dict):
                feature["geometry"] = to_2d(row["geometry"])
            features.append(feature)
        return features

    # ----------------------------------------------------------------- features

    async def fetch_features(
        self,
        layer_id: str,
        bbox: tuple[float, float, float, float] | list[float],
        lang: str = "de",
        grid: int = 8,
        time_instant: str | None = None,
        max_features: int | None = None,
    ) -> list[dict[str, Any]]:
        """Every *current* feature of one layer inside a WGS84 bbox.

        The bbox is split into `grid` x `grid` cells queried concurrently, each
        paginated to exhaustion, then deduplicated by feature id - a feature straddling
        a cell boundary is returned by both cells.

        `time_instant` defaults to the layer's newest published timestamp rather than to
        "no filter": on a time-enabled layer identify returns every vintage of every
        feature, and nothing downstream can tell those apart from distinct features. Pass
        an explicit value to ask for a historical instant.
        """
        if time_instant is None:
            time_instant = await self._newest_timestamp(layer_id, lang)
        minx, miny, maxx, maxy = (float(v) for v in bbox)
        dx = (maxx - minx) / grid
        dy = (maxy - miny) / grid
        cells = [
            (minx + col * dx, miny + row * dy, minx + (col + 1) * dx, miny + (row + 1) * dy)
            for row in range(grid)
            for col in range(grid)
        ]

        results = await asyncio.gather(
            *(self._fetch_cell(layer_id, cell, lang, time_instant) for cell in cells),
            return_exceptions=True,
        )

        features: list[dict[str, Any]] = []
        seen: set[Any] = set()
        failed = 0
        for outcome in results:
            if isinstance(outcome, LayerNotQueryable):
                raise outcome
            if isinstance(outcome, BaseException):
                failed += 1
                continue
            for feature in outcome:
                key = feature.get("id")
                if key is None:
                    features.append(feature)
                elif key not in seen:
                    seen.add(key)
                    features.append(feature)

        if failed:
            # Never silent: a dropped cell is a hole in the map, and the count derived
            # from it would otherwise be reported as a total.
            logger.warning("%s: %d/%d grid cells failed", layer_id, failed, len(cells))
        logger.info("%s: %d unique features from %d cells", layer_id, len(features), len(cells))
        return features[:max_features] if max_features else features

    async def _newest_timestamp(self, layer_id: str, lang: str) -> str | None:
        """The instant a time-enabled layer should be pinned to, or None if it is not one.

        59 of the 896 catalogue layers are time-enabled. For those, identify returns every
        vintage of every feature - the commune layer carries 177 of them, back to 1850 -
        and they are indistinguishable downstream from distinct features: a valley holding
        7 communes is reported as 1228, and their areas summed as if they were neighbours.

        `is_current_jahr` looks like the filter for this and is not: it is False on the
        previous year's rows too, so it silently returns nothing whenever the newest
        published vintage is not the current calendar year.
        """
        config = (await self.layers_config(lang)).get(layer_id) or {}
        if not config.get("timeEnabled"):
            return None
        stamps = [str(t) for t in (config.get("timestamps") or [])]
        return max(stamps) if stamps else None

    async def _fetch_cell(
        self,
        layer_id: str,
        cell: tuple[float, float, float, float],
        lang: str,
        time_instant: str | None,
    ) -> list[dict[str, Any]]:
        envelope = ",".join(str(v) for v in cell)
        params: dict[str, Any] = {
            "geometry": envelope,
            "geometryType": "esriGeometryEnvelope",
            "layers": f"all:{layer_id}",
            "mapExtent": envelope,
            # 1x1 makes tolerance a no-op in map units: we want features intersecting
            # the envelope, not features near a clicked pixel.
            "imageDisplay": "1,1,96",
            "tolerance": 0,
            "sr": 4326,
            "geometryFormat": "geojson",
            "returnGeometry": "true",
            "lang": lang,
            "limit": PAGE,
        }
        if time_instant:
            params["timeInstant"] = time_instant

        out: list[dict[str, Any]] = []
        async with self._semaphore:
            for page in range(MAX_PAGES):
                try:
                    payload = await self._get(IDENTIFY, {**params, "offset": page * PAGE})
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 400:
                        raise LayerNotQueryable(layer_id) from exc
                    raise

                rows = [
                    r
                    for r in payload.get("results", [])
                    # -99 is identify's "no data here" sentinel, not a feature.
                    if r.get("featureId") != -99 and r.get("id") != -99
                ]
                if not rows:
                    break
                for row in rows:
                    geometry = row.get("geometry")
                    if not isinstance(geometry, dict):
                        continue
                    out.append(
                        {
                            "type": "Feature",
                            "id": row.get("featureId") or row.get("id"),
                            "geometry": to_2d(geometry),
                            "properties": row.get("properties") or {},
                        }
                    )
                if len(rows) < PAGE:
                    break
            else:
                logger.warning("%s: cell hit the %d-page cap", layer_id, MAX_PAGES)
        return out

    async def fetch_divisions(
        self, division: DivisionLayer, lang: str = "de"
    ) -> list[list[dict[str, Any]]]:
        """Every current division of one administrative level, nationally, grouped by name.

        Returns one group per named division rather than one feature: a locality is one
        polygon per postcode, and Zürich has 24 of them. Keeping only the first would put
        an eighth of the city on the map and call it Zürich. For the boundary layers every
        group holds exactly one feature, so this is the same result they gave before.

        The commune and district layers are historical series: without a time filter
        Baar comes back once per year of validity since 1850, and the 200-per-page cap
        is then spent entirely on the 19th century. fetch_features pins the newest
        published timestamp for us, which is what makes this a current-boundaries fetch.
        """
        features = await self.fetch_features(division.layer_id, CH_BBOX, lang=lang)

        # Grouped by name, with `objektart_lookup` in the key because the commune layer
        # also carries 13 non-communes - the large lakes and Staatswald Galm, filed as
        # `kantonsgebiet`. One of them, the lake Greifensee, shares its name with a
        # commune, and on a plain name key whichever arrived first shadowed the other.
        groups: dict[tuple[str, Any], list[dict[str, Any]]] = {}
        unnamed = 0
        for feature in features:
            properties = feature.get("properties") or {}
            name = feature_name(properties)
            if name is None:
                unnamed += 1
                continue
            if division.only and name not in division.only:
                continue
            groups.setdefault((name, properties.get("objektart_lookup")), []).append(feature)
        if unnamed:
            logger.warning("%s: %d features had no recognisable name", division.kind, unnamed)
        return list(groups.values())
