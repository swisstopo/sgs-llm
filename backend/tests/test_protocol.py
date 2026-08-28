"""The wire contract: what we accept from the frontend and what we put on the wire."""

from __future__ import annotations

import json

import pytest

from app.protocol import (
    CatalogLayerRef,
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
                "model": "secondary",
                "history": [{"role": "user", "content": "hallo"}],
                "map_context": {"bbox": [7.0, 46.0, 8.2, 46.6], "active_layer_ids": ["a"]},
            }
        )
    )
    assert isinstance(event, UserMessage)
    assert event.id == "m1"
    assert event.language == "de"
    assert event.model == "secondary"
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


def test_model_defaults_to_primary_and_rejects_unknown_choices() -> None:
    event = parse_client_event(
        json.dumps({"type": "user_message", "id": "m1", "content": "hi", "lang": "en"})
    )
    assert isinstance(event, UserMessage)
    assert event.model == "primary"
    assert (
        parse_client_event(
            json.dumps(
                {
                    "type": "user_message",
                    "id": "m2",
                    "content": "hi",
                    "lang": "en",
                    "model": "auto",
                }
            )
        )
        is None
    )


def test_accepts_apertus_as_a_model_choice() -> None:
    event = parse_client_event(
        json.dumps(
            {"type": "user_message", "id": "m1", "content": "hi", "lang": "de", "model": "apertus"}
        )
    )
    assert isinstance(event, UserMessage)
    assert event.model == "apertus"


def test_apertus_is_a_valid_model_in_the_published_client_schema(client_event_validator) -> None:
    """The enum Ageospatial reads from. An additive value they may adopt when ready."""
    payload = {
        "type": "user_message",
        "id": "m1",
        "content": "hi",
        "lang": "de",
        "model": "apertus",
    }

    assert client_event_validator.is_valid(payload)


def test_model_unavailable_validates_against_the_published_schema(server_event_validator) -> None:
    frame = json.loads(
        Error(message_id="m", code="model_unavailable", message="offline until 06:30").frame()
    )

    assert server_event_validator.is_valid(frame)


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
        geometry_type="polygon",
        feature_count=5,
        bbox=(7.0, 46.0, 8.0, 46.5),
        attribution="swisstopo",
        style_hint={"fill_color": "#1c64f2", "opacity": 0.45},  # type: ignore[arg-type]
    )
    frames = [
        Intermediate(message_id="m", step_id="s1", status="finished", label="done", detail="d"),
        Final(
            message_id="m",
            content_markdown="## Answer",
            layers=[layer],
            catalog_layers=[
                CatalogLayerRef(id="ch.bafu.aquaprotect_100", name="Aquaprotect", opacity=0.7)
            ],
            focus_bbox=(7.29, 46.91, 7.5, 46.99),
        ),
        Error(message_id="m", code="timeout", message="too slow"),
        Done(message_id="m"),
    ]
    for event in frames:
        server_event_validator.validate(json.loads(event.frame()))


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
