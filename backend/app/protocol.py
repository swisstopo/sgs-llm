"""Agent WebSocket protocol v1, server side.

Mirrors frontend/src/protocol/v1.ts field for field. docs/protocol.md is normative and
docs/protocol/*.schema.json is what the tests validate emitted frames against; keep all
four in sync.

Two contract rules are enforced here rather than by callers: client events tolerate
unknown fields, and emitted frames omit absent optionals instead of sending null, which
the frontend's guards would reject.
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

ProtocolLang = Literal["de", "fr", "it", "en", "rm"]
SUPPORTED_LANGS: frozenset[str] = frozenset({"de", "fr", "it", "en", "rm"})
DEFAULT_LANG: ProtocolLang = "de"

ErrorCode = Literal["internal", "timeout", "bad_request", "cancelled"]

# [minLon, minLat, maxLon, maxLat] in WGS84.
BBox = tuple[float, float, float, float]


class _ClientModel(BaseModel):
    # Forward compatibility: the frontend may add fields before the backend knows
    # about them, and the contract says servers must tolerate that.
    model_config = ConfigDict(extra="ignore")


class HistoryEntry(_ClientModel):
    role: Literal["user", "assistant"]
    content: str


class MapContext(_ClientModel):
    bbox: BBox
    active_layer_ids: list[str] = Field(default_factory=list)


class UserMessage(_ClientModel):
    type: Literal["user_message"]
    id: str
    content: str
    lang: str = DEFAULT_LANG
    history: list[HistoryEntry] = Field(default_factory=list)
    map_context: MapContext | None = None

    @property
    def language(self) -> ProtocolLang:
        return coerce_lang(self.lang)


class Cancel(_ClientModel):
    type: Literal["cancel"]
    id: str


ClientEvent = UserMessage | Cancel


class _ServerModel(BaseModel):
    def frame(self) -> str:
        """Serialises to a single JSON text frame, omitting absent optionals."""
        return json.dumps(self.model_dump(mode="json", exclude_none=True), ensure_ascii=False)


class StyleHint(_ServerModel):
    fill_color: str | None = None
    stroke_color: str | None = None
    stroke_width: float | None = None
    point_radius: float | None = None
    # Bounded because docs/protocol/server-events.schema.json declares 0..1, and the
    # tests validate emitted frames against that schema.
    opacity: float | None = Field(default=None, ge=0, le=1)


class LayerSpec(_ServerModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    format: Literal["geojson", "mvt"]
    url: str
    dispose_url: str | None = None
    url_expires_at: datetime | None = None
    geometry_type: Literal["point", "line", "polygon"]
    feature_count: int | None = Field(default=None, ge=0)
    truncated: bool | None = None
    bbox: BBox | None = None
    min_zoom: int | None = Field(default=None, ge=0, le=24)
    max_zoom: int | None = Field(default=None, ge=0, le=24)
    attribution: str | None = None
    style_hint: StyleHint | None = None

    @model_validator(mode="after")
    def validate_mvt(self) -> LayerSpec:
        if self.format == "mvt":
            if not all(marker in self.url for marker in ("{z}", "{x}", "{y}")):
                raise ValueError("MVT URLs must contain {z}, {x}, and {y}")
            if self.min_zoom is None or self.max_zoom is None or self.min_zoom > self.max_zoom:
                raise ValueError("MVT layers require an ordered zoom range")
        return self


class CatalogLayerRef(_ServerModel):
    """An official geo.admin.ch layer, named rather than shipped.

    Most Swiss hazard data is raster (WMTS/WMS) and cannot be expressed as a `LayerSpec`,
    which needs a fetchable GeoJSON or generated-MVT URL. But the frontend already renders any
    catalog layer through `LayerService.addOfficialLayer`, resolving WMTS/WMS/GeoJSON from
    layersConfig - so the agent only has to name one. The tiles then come straight from
    swisstopo: nothing is re-hosted, and attribution and legends come along for free.
    """

    id: str
    name: str | None = None
    opacity: float | None = Field(default=None, ge=0, le=1)
    attribution: str | None = None


class Intermediate(_ServerModel):
    type: Literal["intermediate"] = "intermediate"
    message_id: str
    step_id: str
    status: Literal["started", "finished", "failed"]
    label: str
    detail: str | None = None


class Final(_ServerModel):
    type: Literal["final"] = "final"
    message_id: str
    content_markdown: str
    layers: list[LayerSpec] | None = None
    catalog_layers: list[CatalogLayerRef] | None = None
    # `LayerSpec.bbox` covers produced layers, but a catalog layer is national and has no
    # extent of its own, so the area asked about travels separately.
    focus_bbox: BBox | None = None


class Error(_ServerModel):
    type: Literal["error"] = "error"
    message_id: str
    code: ErrorCode
    message: str


class Done(_ServerModel):
    type: Literal["done"] = "done"
    message_id: str


ServerEvent = Intermediate | Final | Error | Done


def coerce_lang(value: object) -> ProtocolLang:
    """A request language, falling back to German for anything unrecognised."""
    if isinstance(value, str) and value in SUPPORTED_LANGS:
        return value  # type: ignore[return-value]
    return DEFAULT_LANG


def parse_client_event(raw: str | bytes) -> ClientEvent | None:
    """Parses one client frame, returning None for anything unrecognised.

    Mirrors the frontend's parseServerEvent: malformed frames and unknown event
    types are dropped silently rather than treated as errors, so neither side can
    be broken by the other adding a message type.
    """
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict):
        return None

    model: type[UserMessage] | type[Cancel]
    match data.get("type"):
        case "user_message":
            model = UserMessage
        case "cancel":
            model = Cancel
        case _:
            return None
    try:
        return model.model_validate(data)
    except ValidationError:
        return None


def coerce_layer_spec(candidate: dict[str, Any]) -> LayerSpec | None:
    """Builds a LayerSpec from loosely-typed tool output, or None if it cannot.

    Tool results come from an MCP server we do not control, so a layer that would
    fail the frontend's isLayerSpec guard is dropped here instead of being sent as
    a frame the browser silently discards.
    """
    try:
        return LayerSpec.model_validate(candidate)
    except ValidationError:
        return None
