"""Strict shared models for private GeoParquet-backed vector tiles."""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit

_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "created_at",
        "expires_at",
        "feature_count",
        "coordinate_count",
        "complete",
        "bbox",
        "crs",
        "geometry_type",
        "min_zoom",
        "fit_zoom",
        "max_zoom",
        "property_columns",
        "property_types",
        "source_sha256",
        "source_bytes",
    }
)
_CHECKSUM = re.compile(r"[0-9a-f]{64}\Z")
_RESERVED_COLUMNS = frozenset({"geometry", "bbox", "__feature_id"})


class InvalidTile(ValueError):
    """The requested slippy-map coordinate is outside the layer contract."""


class TileTooLarge(RuntimeError):
    """One bounded tile exceeded a structural row, feature, or byte ceiling."""


class SourceInvalid(RuntimeError):
    """The private source cannot be safely rendered."""


class RenderTimedOut(RuntimeError):
    """DuckDB did not complete the bounded render before its deadline."""


def _is_int(value: object) -> bool:
    return type(value) is int


def _utc_timestamp(value: datetime, field: str) -> str:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() != UTC.utcoffset(value)
    ):
        raise ValueError(f"{field} must be a UTC datetime")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_utc_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError(f"{field} must be a UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(f"{value[:-1]}+00:00")
    except ValueError as exc:
        raise ValueError(f"{field} must be a valid UTC timestamp") from exc
    if parsed.utcoffset() != UTC.utcoffset(parsed):
        raise ValueError(f"{field} must be a UTC timestamp")
    return parsed


def _string_mapping(value: object, field: str) -> dict[str, str]:
    if type(value) is not dict or any(
        not isinstance(key, str) or not isinstance(item, str) or not item
        for key, item in value.items()
    ):
        raise ValueError(f"{field} must be an object of non-empty string values")
    return dict(value)


@dataclass(frozen=True, slots=True)
class LayerManifest:
    """Canonical commit marker for one immutable private GeoParquet source."""

    schema_version: Literal[1]
    created_at: datetime
    expires_at: datetime
    feature_count: int
    coordinate_count: int
    complete: bool
    bbox: tuple[float, float, float, float]
    crs: str
    geometry_type: Literal["point", "line", "polygon"]
    min_zoom: int
    fit_zoom: int
    max_zoom: int
    property_columns: dict[str, str]
    property_types: dict[str, str]
    source_sha256: str
    source_bytes: int

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        if not _is_int(self.schema_version) or self.schema_version != 1:
            raise ValueError("schema_version must be integer 1")
        _utc_timestamp(self.created_at, "created_at")
        _utc_timestamp(self.expires_at, "expires_at")
        for field, value in (
            ("feature_count", self.feature_count),
            ("coordinate_count", self.coordinate_count),
        ):
            if not _is_int(value) or value < 0:
                raise ValueError(f"{field} must be a non-negative integer")
        if type(self.complete) is not bool:
            raise ValueError("complete must be a boolean")
        if type(self.bbox) is not tuple or len(self.bbox) != 4:
            raise ValueError("bbox must be a four-number tuple")
        if any(type(value) not in (int, float) or not math.isfinite(value) for value in self.bbox):
            raise ValueError("bbox must contain four finite numbers")
        west, south, east, north = self.bbox
        if west > east or south > north:
            raise ValueError("bbox minima must not exceed maxima")
        if self.crs != "OGC:CRS84":
            raise ValueError("crs must be exactly OGC:CRS84")
        if self.geometry_type not in ("point", "line", "polygon"):
            raise ValueError("geometry_type must be point, line, or polygon")
        if (
            any(
                not _is_int(value) or not 0 <= value <= 24
                for value in (self.min_zoom, self.fit_zoom, self.max_zoom)
            )
            or not self.min_zoom <= self.fit_zoom <= self.max_zoom
        ):
            raise ValueError("zoom values must be ordered integers from 0 to 24")
        columns = _string_mapping(self.property_columns, "property_columns")
        types = _string_mapping(self.property_types, "property_types")
        if columns.keys() != types.keys():
            raise ValueError("property_columns and property_types must have the same keys")
        if len(set(columns.values())) != len(columns):
            raise ValueError("physical property columns must be unique")
        if any(
            value in _RESERVED_COLUMNS or value.startswith("__sgs_") for value in columns.values()
        ):
            raise ValueError("physical property column uses a reserved name")
        if not isinstance(self.source_sha256, str) or not _CHECKSUM.fullmatch(self.source_sha256):
            raise ValueError("source_sha256 must be 64 lowercase hexadecimal characters")
        if not _is_int(self.source_bytes) or self.source_bytes <= 0:
            raise ValueError("source_bytes must be a positive integer")

    def to_json(self) -> bytes:
        """Serialize a canonical UTF-8 JSON object."""
        self._validate()
        payload = {
            "schema_version": self.schema_version,
            "created_at": _utc_timestamp(self.created_at, "created_at"),
            "expires_at": _utc_timestamp(self.expires_at, "expires_at"),
            "feature_count": self.feature_count,
            "coordinate_count": self.coordinate_count,
            "complete": self.complete,
            "bbox": list(self.bbox),
            "crs": self.crs,
            "geometry_type": self.geometry_type,
            "min_zoom": self.min_zoom,
            "fit_zoom": self.fit_zoom,
            "max_zoom": self.max_zoom,
            "property_columns": self.property_columns,
            "property_types": self.property_types,
            "source_sha256": self.source_sha256,
            "source_bytes": self.source_bytes,
        }
        return json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @classmethod
    def from_json(cls, encoded: bytes) -> LayerManifest:
        """Parse a manifest without accepting coercions, extensions, or local time."""
        if not isinstance(encoded, bytes):
            raise ValueError("manifest JSON must be bytes")
        try:
            payload: Any = json.loads(encoded.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("manifest JSON must be valid UTF-8 JSON") from exc
        if type(payload) is not dict:
            raise ValueError("manifest JSON must contain an object")
        if payload.keys() != _MANIFEST_KEYS:
            missing = sorted(_MANIFEST_KEYS - payload.keys())
            extra = sorted(payload.keys() - _MANIFEST_KEYS)
            raise ValueError(f"manifest must have exact keys; missing={missing}, extra={extra}")
        bbox = payload["bbox"]
        if type(bbox) is not list or len(bbox) != 4:
            raise ValueError("bbox must be a four-number array")
        return cls(
            schema_version=payload["schema_version"],
            created_at=_parse_utc_timestamp(payload["created_at"], "created_at"),
            expires_at=_parse_utc_timestamp(payload["expires_at"], "expires_at"),
            feature_count=payload["feature_count"],
            coordinate_count=payload["coordinate_count"],
            complete=payload["complete"],
            bbox=tuple(bbox),
            crs=payload["crs"],
            geometry_type=payload["geometry_type"],
            min_zoom=payload["min_zoom"],
            fit_zoom=payload["fit_zoom"],
            max_zoom=payload["max_zoom"],
            property_columns=_string_mapping(payload["property_columns"], "property_columns"),
            property_types=_string_mapping(payload["property_types"], "property_types"),
            source_sha256=payload["source_sha256"],
            source_bytes=payload["source_bytes"],
        )


@dataclass(frozen=True, slots=True, repr=False)
class SourceRef:
    """A parameter-bound absolute local file or private S3 object reference."""

    uri: str

    def __post_init__(self) -> None:
        if not isinstance(self.uri, str) or not self.uri or self.uri != self.uri.strip():
            raise ValueError("source must be a non-empty canonical reference")
        if "\x00" in self.uri:
            raise ValueError("source reference contains an invalid character")
        parsed = urlsplit(self.uri)
        if parsed.scheme:
            if (
                parsed.scheme != "s3"
                or not parsed.netloc
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
                or parsed.path in ("", "/")
            ):
                raise ValueError("source must be an absolute local file or S3 object")
        elif not Path(self.uri).is_absolute():
            raise ValueError("source must be an absolute local file or S3 object")

    @property
    def is_s3(self) -> bool:
        return self.uri.startswith("s3://")

    def __repr__(self) -> str:
        return "SourceRef(<private>)"


@dataclass(frozen=True, slots=True)
class TileCoord:
    z: int
    x: int
    y: int

    def validate(self, min_zoom: int, max_zoom: int | None = None) -> None:
        """Validate a coordinate against the manifest range and slippy bounds."""
        if max_zoom is None:
            max_zoom = min_zoom
            min_zoom = 0
        if any(type(value) is not int for value in (self.z, self.x, self.y)):
            raise InvalidTile("tile coordinates must be integers")
        if self.z < min_zoom or self.z > max_zoom:
            raise InvalidTile("tile zoom is outside the layer range")
        edge = 2**self.z
        if not 0 <= self.x < edge or not 0 <= self.y < edge:
            raise InvalidTile("tile coordinate is outside the zoom grid")


@dataclass(frozen=True, slots=True)
class RenderLimits:
    """Per-request DuckDB and result ceilings for one isolated tile render."""

    threads: int = 1
    memory_bytes: int = 512 * 1024 * 1024
    max_spill_bytes: int = 512 * 1024 * 1024
    timeout_seconds: float = 30.0
    max_rows_examined: int = 100_000
    max_features_encoded: int = 20_000
    max_mvt_bytes: int = 1024 * 1024
    spill_directory: Path | None = None
    extension_directory: Path | None = None
    s3_endpoint_url: str | None = None

    def __post_init__(self) -> None:
        if type(self.threads) is not int or self.threads != 1:
            raise ValueError("tile rendering requires exactly one thread")
        for field, value in (
            ("memory_bytes", self.memory_bytes),
            ("max_spill_bytes", self.max_spill_bytes),
            ("max_rows_examined", self.max_rows_examined),
            ("max_features_encoded", self.max_features_encoded),
            ("max_mvt_bytes", self.max_mvt_bytes),
        ):
            if type(value) is not int or value <= 0:
                raise ValueError(f"{field} must be a positive integer")
        if (
            type(self.timeout_seconds) not in (int, float)
            or not math.isfinite(self.timeout_seconds)
            or self.timeout_seconds <= 0
        ):
            raise ValueError("timeout_seconds must be a positive finite number")
        for path_field, path_value in (
            ("spill_directory", self.spill_directory),
            ("extension_directory", self.extension_directory),
        ):
            if path_value is not None and (
                not isinstance(path_value, Path) or not path_value.is_absolute()
            ):
                raise ValueError(f"{path_field} must be an absolute Path")
        if self.extension_directory is not None and not self.extension_directory.is_dir():
            raise ValueError("extension_directory must exist and be a directory")
        if self.s3_endpoint_url is not None:
            parsed = urlsplit(self.s3_endpoint_url)
            if (
                not isinstance(self.s3_endpoint_url, str)
                or self.s3_endpoint_url != self.s3_endpoint_url.strip()
                or parsed.scheme not in {"http", "https"}
                or not parsed.netloc
                or parsed.username is not None
                or parsed.password is not None
                or parsed.path not in {"", "/"}
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("s3_endpoint_url must be a bare HTTP(S) origin")
