"""Thin wrappers over the public geo.admin.ch APIs, mirroring frontend/src/swisstopo/.

identify is used as a bbox feature query rather than a click query. Response shapes were
verified against the live API on 2026-07-30.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from .cantons import CANTON_NAMES, canton_code

logger = logging.getLogger(__name__)

API3 = "https://api3.geo.admin.ch/rest/services"

# The API's own maximum for identify; the default is 50.
IDENTIFY_MAX = 200

# ~1 MB per language and rarely changing, so fetched once and kept. Carries how a layer
# renders, and the `tooltip` flag used as the queryability hint.
LAYERS_CONFIG = f"{API3}/all/MapServer/layersConfig"

# Search results wrap the matched substring in markup for highlighting.
_TAGS = re.compile(r"<[^>]+>")

_TIMEOUT = httpx.Timeout(20.0, connect=10.0)

# Ordered by how area-like the result is. A canton or commune polygon is a far better
# answer to "in Valais" than a gazetteer point that merely shares a prefix.
_LOCATION_ORIGINS = ("kantone", "district", "gg25", "gazetteer")


class LayerNotQueryable(Exception):
    """The dataset exists but cannot be queried feature-by-feature.

    identify answers HTTP 400 for these - raster layers, warning maps, anything without
    a queryable feature table. That is a *fact about the dataset*, not a transport
    failure, and it has to reach the model as one: told only "the tool failed", models
    retry the same call until they run out of iterations.
    """

    def __init__(self, layer_id: str) -> None:
        super().__init__(layer_id)
        self.layer_id = layer_id


def strip_markup(text: str) -> str:
    return _TAGS.sub("", text or "").strip()


def parse_box2d(value: Any) -> list[float] | None:
    """Parses SearchServer's `BOX(minx miny,maxx maxy)` into [w, s, e, n]."""
    if not isinstance(value, str):
        return None
    inner = value.strip()
    if not inner.upper().startswith("BOX(") or not inner.endswith(")"):
        return None
    try:
        low, high = inner[4:-1].split(",")
        west, south = (float(v) for v in low.split())
        east, north = (float(v) for v in high.split())
    except ValueError:
        return None
    return [min(west, east), min(south, north), max(west, east), max(south, north)]


def _pad_degenerate(bbox: list[float], *, pad: float = 0.02) -> list[float]:
    """Gives a point result a usable extent.

    Gazetteer hits come back as a zero-area box, which would make a map zoom to an
    infinitely small area; ~2 km of padding makes it a viewport.
    """
    west, south, east, north = bbox
    if east - west < 1e-9:
        west, east = west - pad, east + pad
    if north - south < 1e-9:
        south, north = south - pad, north + pad
    return [west, south, east, north]


class Swisstopo:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client
        self._owned = client is None
        self._layers_config: dict[str, dict[str, Any]] = {}

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

    async def layers_config(self, lang: str) -> dict[str, dict[str, Any]]:
        """layersConfig for one language, fetched once and kept.

        A failure is not cached: one transient error would otherwise make every layer
        report `known: false` for the rest of the run, which silently depresses a
        benchmark pass rate.
        """
        if not self._layers_config.get(lang):
            try:
                self._layers_config[lang] = await self._get(LAYERS_CONFIG, {"lang": lang})
            except Exception:
                logger.warning("layersConfig unavailable for %s", lang, exc_info=True)
                return {}
        return self._layers_config[lang]

    async def layer_capabilities(self, layer_id: str, lang: str) -> dict[str, Any]:
        """How a layer can be used: rendered as a map layer, queried for features, or both.

        `queryable` is a hint derived from layersConfig's `tooltip`, not a guarantee:
        identify answers for some layers it reports false. Treat a LayerNotQueryable from
        identify as the authority.
        """
        config = (await self.layers_config(lang)).get(layer_id)
        if not isinstance(config, dict):
            return {"known": False, "displayable": False, "queryable": False}
        return {
            "known": True,
            "type": config.get("type"),
            "label": config.get("label"),
            # Everything layersConfig describes can be rendered by the client; only
            # background-less entries with no service type cannot.
            "displayable": config.get("type") in ("wmts", "wms", "geojson", "aggregate"),
            # `tooltip`, not `queryable`: layersConfig has no `queryable` key at all (0 of
            # 896 entries), so reading it reported every layer as unqueryable and the agent
            # never fetched any features. `tooltip` is the flag map.geo.admin.ch uses, and
            # it is a hint rather than a guarantee - identify answers for some layers with
            # tooltip false, so the authority is LayerNotQueryable from identify itself.
            "queryable": bool(config.get("tooltip")),
        }

    async def search_layers(self, query: str, lang: str, limit: int = 8) -> list[dict[str, Any]]:
        """Official datasets matching a free-text query, with how each can be used."""
        payload = await self._get(
            f"{API3}/ech/SearchServer",
            {"searchText": query, "type": "layers", "lang": lang, "limit": limit},
        )
        found: list[dict[str, Any]] = []
        for result in payload.get("results", [])[:limit]:
            attrs = result.get("attrs", {}) or {}
            layer_id = attrs.get("layer")
            if not isinstance(layer_id, str):
                continue
            detail = strip_markup(str(attrs.get("detail", "")))
            caps = await self.layer_capabilities(layer_id, lang)
            found.append(
                {
                    "layer_id": layer_id,
                    "title": strip_markup(str(attrs.get("label", layer_id))),
                    # The detail field carries the whole dataset abstract, which is
                    # often thousands of characters; the model only needs the gist.
                    "summary": detail[:400],
                    "queryable": caps["queryable"],
                    "displayable": caps["displayable"],
                }
            )
        return found

    async def search_locations(self, query: str, lang: str, limit: int = 5) -> list[dict[str, Any]]:
        """Places, communes, districts and cantons matching a free-text query.

        A canton name in any national language is resolved through its two-letter code
        first, because the canton index does not match all of them (see cantons.py).
        """
        code = canton_code(query)
        attempts: list[tuple[str, str]] = []
        if code is not None:
            attempts.append((code, "kantone"))
        attempts.append((query, ",".join(_LOCATION_ORIGINS)))

        for search_text, origins in attempts:
            payload = await self._get(
                f"{API3}/ech/SearchServer",
                {
                    "searchText": search_text,
                    "type": "locations",
                    "origins": origins,
                    "lang": lang,
                    "sr": 4326,
                    "limit": limit,
                },
            )
            places: list[dict[str, Any]] = []
            for result in payload.get("results", [])[:limit]:
                attrs = result.get("attrs", {}) or {}
                bbox = parse_box2d(attrs.get("geom_st_box2d"))
                if bbox is None:
                    continue
                label = strip_markup(str(attrs.get("label", "")))
                if code is not None and origins == "kantone":
                    # Report the name the user used, not only the API's single form.
                    label = f"{label} ({CANTON_NAMES[code][0]}, {code})"
                places.append(
                    {
                        "name": label,
                        "kind": str(attrs.get("origin", "")),
                        "bbox": _pad_degenerate(bbox),
                    }
                )
            if places:
                return places
        return []

    async def identify_features(
        self,
        layer_id: str,
        bbox: list[float],
        lang: str,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Features of one layer inside a WGS84 bbox, as GeoJSON features.

        identify is used as a bbox query here: `sr=4326` and `geometryFormat=geojson`
        return WGS84 GeoJSON directly, so nothing needs reprojecting before the browser
        sees it. `tolerance=0` because the geometry is an envelope, not a click point.
        """
        envelope = ",".join(str(v) for v in bbox)
        try:
            payload = await self._identify(layer_id, envelope, lang, limit)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 400:
                raise LayerNotQueryable(layer_id) from exc
            raise

        features: list[dict[str, Any]] = []
        for result in payload.get("results", []):
            geometry = result.get("geometry")
            if not isinstance(geometry, dict):
                continue
            features.append(
                {
                    "type": "Feature",
                    "id": result.get("featureId") or result.get("id"),
                    "geometry": geometry,
                    "properties": result.get("properties") or {},
                }
            )
        return features

    async def _identify(
        self, layer_id: str, envelope: str, lang: str, limit: int
    ) -> dict[str, Any]:
        return await self._get(
            f"{API3}/all/MapServer/identify",
            {
                "geometry": envelope,
                "geometryType": "esriGeometryEnvelope",
                "layers": f"all:{layer_id}",
                "mapExtent": envelope,
                "imageDisplay": "100,100,96",
                "tolerance": 0,
                "sr": 4326,
                "geometryFormat": "geojson",
                "lang": lang,
                "limit": min(limit, IDENTIFY_MAX),
            },
        )
