"""The wire contract: what we accept from the frontend and what we put on the wire."""

from __future__ import annotations

import json

import pytest
from jsonschema.exceptions import ValidationError as SchemaValidationError
from pydantic import ValidationError as PydanticValidationError

from app.protocol import (
    Done,
    Error,
    Final,
    Intermediate,
    LayerSpec,
    UserMessage,
    coerce_layer_spec,
    parse_client_event,
)


def test_parses_a_user_message() -> None:
    event = parse_client_event(
        json.dumps(
            {
                "type": "user_message",
                "id": "m1",
                "content": "Zeige mir Hochwassergefahren im Wallis",
                "lang": "de",
                "history": [{"role": "user", "content": "hallo"}],
                "map_context": {"bbox": [7.0, 46.0, 8.2, 46.6], "active_layer_ids": ["a"]},
            }
        )
    )
    assert isinstance(event, UserMessage)
    assert event.id == "m1"
    assert event.language == "de"
    assert event.map_context is not None
    assert event.map_context.bbox == (7.0, 46.0, 8.2, 46.6)


def test_tolerates_unknown_fields_and_event_types() -> None:
    """Forward compatibility: the frontend may ship a field before we know it."""
    event = parse_client_event(
        json.dumps({"type": "user_message", "id": "m1", "content": "hi", "future_field": 42})
    )
    assert isinstance(event, UserMessage)
    assert parse_client_event(json.dumps({"type": "final_delta", "id": "m1"})) is None


@pytest.mark.parametrize(
    "raw",
    [
        "not json",
        "[]",
        '{"type": "user_message"}',
        '{"type": "cancel"}',
        '{"type": "user_message", "id": 5, "content": "x"}',
    ],
)
def test_rejects_malformed_frames(raw: str) -> None:
    assert parse_client_event(raw) is None


def test_unknown_language_falls_back_to_german() -> None:
    event = parse_client_event(
        json.dumps({"type": "user_message", "id": "m1", "content": "hi", "lang": "es"})
    )
    assert isinstance(event, UserMessage)
    assert event.language == "de"


def test_romansh_is_supported() -> None:
    event = parse_client_event(
        json.dumps({"type": "user_message", "id": "m1", "content": "hi", "lang": "rm"})
    )
    assert isinstance(event, UserMessage)
    assert event.language == "rm"


def test_frames_omit_absent_optionals() -> None:
    """The frontend's guards accept `undefined`, not `null`."""
    frame = json.loads(
        Intermediate(message_id="m", step_id="s1", status="started", label="x").frame()
    )
    assert "detail" not in frame

    final = json.loads(Final(message_id="m", content_markdown="answer").frame())
    assert "layers" not in final


def test_frames_validate_against_the_published_schema(server_event_validator) -> None:
    layer = LayerSpec(
        id="l1",
        name="Hochwasser",
        format="geojson",
        url="https://example.test/a.geojson",
        url_expires_at="2026-08-11T01:00:00Z",  # type: ignore[arg-type]
        truncated=True,
        geometry_type="polygon",
        feature_count=5,
        bbox=(7.0, 46.0, 8.0, 46.5),
        attribution="swisstopo",
        style_hint={"fill_color": "#1c64f2", "opacity": 0.45},  # type: ignore[arg-type]
    )
    frames = [
        Intermediate(message_id="m", step_id="s1", status="finished", label="done", detail="d"),
        Final(message_id="m", content_markdown="## Answer", layers=[layer]),
        Error(message_id="m", code="timeout", message="too slow"),
        Done(message_id="m"),
    ]
    for event in frames:
        server_event_validator.validate(json.loads(event.frame()))


def test_mvt_layer_spec_carries_tile_templates_and_zoom_range(server_event_validator) -> None:
    layer = LayerSpec(
        id="roads",
        name="Roads",
        format="mvt",
        url="https://tiles.test/tiles/token/{z}/{x}/{y}.mvt",
        dispose_url="/data/layers/token",
        url_expires_at="2026-08-11T10:00:00Z",  # type: ignore[arg-type]
        geometry_type="line",
        min_zoom=0,
        max_zoom=16,
    )
    frame = json.loads(Final(message_id="m", content_markdown="ok", layers=[layer]).frame())
    server_event_validator.validate(frame)
    assert frame["layers"][0]["url"].endswith("/{z}/{x}/{y}.mvt")
    assert "fallback_url" not in frame["layers"][0]


def test_mvt_layer_rejects_a_template_without_xyz() -> None:
    candidate = {
        "id": "roads",
        "name": "Roads",
        "format": "mvt",
        "url": "/data/tiles/token/{z}/{x}/{y}.mvt",
        "geometry_type": "line",
        "min_zoom": 0,
        "max_zoom": 16,
    }
    candidate["url"] = "/data/tiles/token/all.mvt"
    with pytest.raises(
        PydanticValidationError, match=r"MVT URLs must contain \{z\}, \{x\}, and \{y\}"
    ):
        LayerSpec.model_validate(candidate)


def test_mvt_layer_rejects_removed_fallback_plumbing() -> None:
    with pytest.raises(PydanticValidationError):
        LayerSpec.model_validate(
            {
                "id": "roads",
                "name": "Roads",
                "format": "mvt",
                "url": "/data/tiles/token/{z}/{x}/{y}.mvt",
                "fallback_url": "https://unused.test/tile.mvt",
                "geometry_type": "line",
                "min_zoom": 0,
                "max_zoom": 16,
            }
        )


def test_published_schema_rejects_removed_fallback_plumbing(server_event_validator) -> None:
    frame = {
        "type": "final",
        "message_id": "m",
        "content_markdown": "ok",
        "layers": [
            {
                "id": "roads",
                "name": "Roads",
                "format": "mvt",
                "url": "/data/tiles/token/{z}/{x}/{y}.mvt",
                "fallback_url": "https://unused.test/{z}/{x}/{y}.mvt",
                "geometry_type": "line",
                "min_zoom": 0,
                "max_zoom": 16,
            }
        ],
    }
    with pytest.raises(SchemaValidationError):
        server_event_validator.validate(frame)


@pytest.mark.parametrize(
    ("min_zoom", "max_zoom"),
    [(None, 16), (0, None), (16, 0)],
)
def test_mvt_layer_rejects_missing_or_inverted_zoom_bounds(
    min_zoom: int | None, max_zoom: int | None
) -> None:
    candidate = {
        "id": "roads",
        "name": "Roads",
        "format": "mvt",
        "url": "/data/tiles/token/{z}/{x}/{y}.mvt",
        "geometry_type": "line",
        "min_zoom": min_zoom,
        "max_zoom": max_zoom,
    }

    with pytest.raises(PydanticValidationError, match="MVT layers require an ordered zoom range"):
        LayerSpec.model_validate(candidate)


def test_published_schema_rejects_an_inverted_mvt_zoom_range(server_event_validator) -> None:
    frame = {
        "type": "final",
        "message_id": "m",
        "content_markdown": "ok",
        "layers": [
            {
                "id": "roads",
                "name": "Roads",
                "format": "mvt",
                "url": "https://tiles.test/tiles/token/{z}/{x}/{y}.mvt",
                "geometry_type": "line",
                "min_zoom": 16,
                "max_zoom": 0,
            }
        ],
    }

    with pytest.raises(SchemaValidationError):
        server_event_validator.validate(frame)


def test_coerce_layer_spec_rejects_what_the_frontend_would_discard() -> None:
    assert coerce_layer_spec({"id": "a", "name": "b", "format": "shapefile", "url": "u"}) is None
    assert coerce_layer_spec({"id": "a", "name": "b", "format": "geojson"}) is None
    assert (
        coerce_layer_spec(
            {
                "id": "a",
                "name": "b",
                "format": "geojson",
                "url": "https://x.test/a.geojson",
                "geometry_type": "hexagon",
            }
        )
        is None
    )
    assert (
        coerce_layer_spec(
            {
                "id": "a",
                "name": "b",
                "format": "geojson",
                "url": "https://x.test/a.geojson",
                "geometry_type": "point",
            }
        )
        is not None
    )
