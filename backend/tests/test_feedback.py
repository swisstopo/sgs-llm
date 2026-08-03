"""POST /feedback.

The accepted payload and the status codes are a contract with the existing frontend
(frontend/src/feedback/submitFeedback.ts) and with mock-agent, so switching backends
must need no frontend change.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.feedback import CATEGORIES, router
from tests.conftest import FakeStore


@pytest.fixture
def client(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> Any:
    get_settings.cache_clear()
    monkeypatch.setattr("app.feedback.get_settings", lambda: settings)
    app = FastAPI()
    app.include_router(router)
    app.state.store = FakeStore()
    app.state.settings = settings
    test_client = TestClient(app)
    test_client.store = app.state.store  # type: ignore[attr-defined]
    return test_client


def test_the_categories_match_the_frontend() -> None:
    """frontend/src/feedback/submitFeedback.ts is the source of this list."""
    assert {"bug", "feature", "improvement", "question", "other"} == CATEGORIES


def test_a_valid_submission_is_stored(client: Any) -> None:
    response = client.post(
        "/feedback",
        json={
            "category": "improvement",
            "message": "Die Karte könnte schneller laden.",
            "email": "someone@example.test",
            "lang": "de",
        },
    )
    assert response.status_code == 204
    assert len(client.store.feedback) == 1
    entry = client.store.feedback[0]
    assert entry["category"] == "improvement"
    assert entry["email"] == "someone@example.test"
    assert entry["lang"] == "de"


def test_email_is_optional(client: Any) -> None:
    response = client.post("/feedback", json={"category": "bug", "message": "x", "lang": "fr"})
    assert response.status_code == 204
    assert client.store.feedback[0]["email"] is None


@pytest.mark.parametrize(
    "payload",
    [
        {"category": "nonsense", "message": "x"},
        {"category": "bug"},
        {"category": "bug", "message": ""},
        {"category": "bug", "message": "   "},
        {"message": "no category"},
        {"category": "bug", "message": "x", "email": 42},
        [],
        "a string",
    ],
)
def test_invalid_payloads_are_rejected(client: Any, payload: Any) -> None:
    assert client.post("/feedback", json=payload).status_code == 400


def test_malformed_json_is_a_400_not_a_500(client: Any) -> None:
    response = client.post(
        "/feedback", content=b"{not json", headers={"content-type": "application/json"}
    )
    assert response.status_code == 400


def test_an_oversized_body_is_refused(client: Any) -> None:
    response = client.post(
        "/feedback",
        content=b'{"category":"bug","message":"' + b"x" * 40_000 + b'"}',
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413
    assert client.store.feedback == []


def test_an_unknown_language_falls_back_rather_than_failing(client: Any) -> None:
    response = client.post(
        "/feedback", json={"category": "other", "message": "hi", "lang": "klingon"}
    )
    assert response.status_code == 204
    assert client.store.feedback[0]["lang"] == "de"


def test_preflight_advertises_the_key_header(client: Any) -> None:
    response = client.options("/feedback")
    assert response.status_code == 204
    allowed = response.headers["access-control-allow-headers"]
    assert "content-type" in allowed
    assert "x-api-key" in allowed


def test_cors_is_permissive_like_the_presigned_url_path(client: Any) -> None:
    response = client.post("/feedback", json={"category": "bug", "message": "x"})
    assert response.headers["access-control-allow-origin"] == "*"


def test_the_key_is_enforced_only_when_configured(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.api_key = "s3cret"
    get_settings.cache_clear()
    monkeypatch.setattr("app.feedback.get_settings", lambda: settings)
    app = FastAPI()
    app.include_router(router)
    app.state.store = FakeStore()
    client = TestClient(app)

    payload = {"category": "bug", "message": "x"}
    assert client.post("/feedback", json=payload).status_code == 401
    assert client.post("/feedback", json=payload, headers={"x-api-key": "wrong"}).status_code == 401
    assert (
        client.post("/feedback", json=payload, headers={"x-api-key": "s3cret"}).status_code == 204
    )


def test_a_storage_failure_does_not_lose_the_users_submission(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Asking someone to retype their feedback because our evaluation table was down is
    the wrong trade."""

    class BrokenStore(FakeStore):
        async def record_feedback(self, **kwargs: Any) -> str:
            raise RuntimeError("dynamodb is down")

    get_settings.cache_clear()
    monkeypatch.setattr("app.feedback.get_settings", lambda: settings)
    app = FastAPI()
    app.include_router(router)
    app.state.store = BrokenStore()

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/feedback", json={"category": "bug", "message": "x"})
    assert response.status_code == 204
