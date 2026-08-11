"""Strict external layer-manifest contract."""

from __future__ import annotations

import importlib
import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest


def manifest_class() -> type[Any]:
    return importlib.import_module("tile_server.model").LayerManifest


def valid_manifest() -> Any:
    return manifest_class()(
        schema_version=1,
        created_at=datetime(2026, 8, 10, 12, tzinfo=UTC),
        expires_at=datetime(2026, 8, 11, 12, tzinfo=UTC),
        feature_count=2,
        coordinate_count=5,
        complete=True,
        bbox=(6.0, 46.0, 8.2, 46.2),
        crs="OGC:CRS84",
        geometry_type="polygon",
        min_zoom=0,
        fit_zoom=7,
        max_zoom=14,
        property_columns={"name": "name"},
        property_types={"name": "string"},
        source_sha256="1" * 64,
        source_bytes=1234,
    )


def test_manifest_json_round_trips_deterministically_with_utc_z_timestamps() -> None:
    manifest = valid_manifest()

    encoded = manifest.to_json()

    assert isinstance(encoded, bytes)
    assert b'"created_at":"2026-08-10T12:00:00Z"' in encoded
    assert b'"expires_at":"2026-08-11T12:00:00Z"' in encoded
    assert manifest_class().from_json(encoded) == manifest
    assert manifest.to_json() == encoded


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda value: value.__setitem__("unexpected", 1), "exact keys"),
        (lambda value: value.__setitem__("schema_version", True), "schema_version"),
        (lambda value: value.__setitem__("feature_count", True), "feature_count"),
        (
            lambda value: value.__setitem__("created_at", "2026-08-10T14:00:00+02:00"),
            "UTC",
        ),
        (lambda value: value.__setitem__("bbox", [8.0, 46.0, 6.0, 46.2]), "bbox"),
        (lambda value: value.__setitem__("geometry_type", "circle"), "geometry_type"),
        (lambda value: value.__setitem__("fit_zoom", 15), "zoom"),
        (lambda value: value.__setitem__("property_types", {}), "same keys"),
        (lambda value: value.__setitem__("source_sha256", "A" * 64), "source_sha256"),
        (lambda value: value.__setitem__("source_bytes", 0), "source_bytes"),
    ],
)
def test_manifest_from_json_rejects_wrong_keys_types_and_values(
    mutation: Any, match: str
) -> None:
    payload = json.loads(valid_manifest().to_json())
    mutation(payload)

    with pytest.raises(ValueError, match=match):
        manifest_class().from_json(json.dumps(payload).encode())


def test_manifest_rejects_duplicate_or_reserved_physical_property_columns() -> None:
    manifest = valid_manifest()

    with pytest.raises(ValueError, match="unique"):
        replace(
            manifest,
            property_columns={"name": "visible", "ref": "visible"},
            property_types={"name": "string", "ref": "string"},
        )
    with pytest.raises(ValueError, match="reserved"):
        replace(
            manifest,
            property_columns={"name": "__sgs_hidden"},
            property_types={"name": "string"},
        )


def test_manifest_constructor_rejects_non_utc_timestamps() -> None:
    manifest = valid_manifest()

    with pytest.raises(ValueError, match="UTC"):
        replace(manifest, created_at=datetime(2026, 8, 10, 12))


def test_manifest_constructor_and_json_require_exact_ogc_crs84() -> None:
    manifest = valid_manifest()

    with pytest.raises(ValueError, match="OGC:CRS84"):
        replace(manifest, crs="EPSG:4326")

    payload = json.loads(manifest.to_json())
    payload["crs"] = "EPSG:4326"
    with pytest.raises(ValueError, match="OGC:CRS84"):
        manifest_class().from_json(json.dumps(payload).encode())


@pytest.mark.parametrize("encoded", [b"not-json", b"[]", b"\xff"])
def test_manifest_from_json_rejects_malformed_or_non_object_payloads(
    encoded: bytes,
) -> None:
    with pytest.raises(ValueError, match="manifest JSON"):
        manifest_class().from_json(encoded)
