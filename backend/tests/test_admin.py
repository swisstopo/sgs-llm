from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.admin import router
from app.admin_users import AdminUserStore
from app.config import Settings


class AdminStore:
    def __init__(self) -> None:
        self.queries: list[tuple[str, str]] = []

    async def query_day(self, *, table_name: str, log_date: str, **_: Any) -> Any:
        self.queries.append((table_name, log_date))
        if table_name == "turns":
            return (
                [
                    {
                        "conversation_id": "c1",
                        "message_id": "m1",
                        "log_date": log_date,
                        "ts": f"{log_date}T12:00:00Z",
                        "lang": "de",
                        "user_message": "Where?",
                        "assistant_markdown": "Here.",
                        "latency_ms": 500,
                        "model_id": "test-model",
                    }
                ],
                None,
            )
        return (
            [
                {
                    "id": "p1",
                    "entry_type": "onboarding",
                    "log_date": log_date,
                    "ts": f"{log_date}T10:00:00Z",
                    "lang": "fr",
                    "user_group": "research_education",
                    "geodata_experience": "advanced",
                    "intended_use": "find_data",
                    "consent_version": "v2",
                    "expires_at": 999,
                }
            ]
            + (
                [
                    {
                        "id": "p2",
                        "entry_type": "onboarding",
                        "log_date": log_date,
                        "ts": f"{log_date}T11:00:00Z",
                        "lang": "de",
                        "geodata_experience": "new",
                        "consent_version": "v2",
                    }
                ]
                if log_date == "2026-08-18"
                else []
            ),
            None,
        )


class GroupedConversationStore(AdminStore):
    async def query_day(self, *, table_name: str, log_date: str, **_: Any) -> Any:
        if table_name != "turns":
            return await super().query_day(table_name=table_name, log_date=log_date)
        return (
            [
                {
                    "conversation_id": "c1",
                    "message_id": "m2",
                    "turn": f"{log_date}T12:05:00Z#m2",
                    "log_date": log_date,
                    "ts": f"{log_date}T12:05:00Z",
                    "lang": "en",
                    "user_message": "And what about Bern?",
                    "assistant_markdown": "Bern is here.",
                    "model_id": "test-model",
                    "tool_calls": ["search_locations"],
                    "latency_ms": 800,
                    "input_tokens": 120,
                    "output_tokens": 30,
                    "layer_count": 1,
                    "expires_at": 999,
                },
                {
                    "conversation_id": "c2",
                    "message_id": "m1",
                    "turn": f"{log_date}T11:00:00Z#m1",
                    "log_date": log_date,
                    "ts": f"{log_date}T11:00:00Z",
                    "lang": "de",
                    "user_message": "Zeige Zürich",
                    "assistant_markdown": "Hier ist Zürich.",
                    "expires_at": 999,
                },
                {
                    "conversation_id": "c1",
                    "message_id": "m1",
                    "turn": f"{log_date}T12:00:00Z#m1",
                    "log_date": log_date,
                    "ts": f"{log_date}T12:00:00Z",
                    "lang": "en",
                    "user_message": "Show me Basel",
                    "assistant_markdown": "Basel is here.",
                    "model_id": "test-model",
                    "tool_calls": ["search_locations", "display_layer"],
                    "latency_ms": 1200,
                    "input_tokens": 180,
                    "output_tokens": 50,
                    "layer_count": 1,
                    "expires_at": 999,
                },
            ],
            None,
        )


class MixedSubmissionStore(AdminStore):
    async def query_day(
        self,
        *,
        table_name: str,
        log_date: str,
        limit: int = 50,
        exclusive_start_key: dict[str, Any] | None = None,
        **_: Any,
    ) -> Any:
        if table_name == "turns":
            return await super().query_day(table_name=table_name, log_date=log_date)
        submissions = [
            {
                "id": "f1",
                "log_date": log_date,
                "ts": f"{log_date}T12:00:00Z",
                "category": "other",
                "message": "First feedback",
                "lang": "en",
            },
            {
                "id": "p1",
                "entry_type": "onboarding",
                "log_date": log_date,
                "ts": f"{log_date}T11:00:00Z",
                "lang": "en",
                "user_group": "private_sector",
                "geodata_experience": "occasional",
                "intended_use": "create_map",
                "consent_version": "v2",
            },
            {
                "id": "f2",
                "log_date": log_date,
                "ts": f"{log_date}T10:00:00Z",
                "category": "question",
                "message": "Second feedback",
                "lang": "de",
            },
            {
                "id": "p2",
                "entry_type": "onboarding",
                "log_date": log_date,
                "ts": f"{log_date}T09:00:00Z",
                "lang": "de",
                "user_group": "public_administration",
                "geodata_experience": "advanced",
                "intended_use": "find_data",
                "consent_version": "v2",
            },
        ]
        start = int((exclusive_start_key or {}).get("offset", 0))
        end = min(start + limit, len(submissions))
        next_key = {"offset": end} if end < len(submissions) else None
        return submissions[start:end], next_key


@pytest.fixture
def client(tmp_path: Any) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.state.settings = Settings(
        allowed_origins="http://127.0.0.1:5173",
        conversation_table="turns",
        feedback_table="feedback",
    )
    app.state.admin_users = AdminUserStore(str(tmp_path / "admins.sqlite3"))
    app.state.admin_users.initialize()
    app.state.admin_users.create_user("admin@example.ch", "CorrectHorse!1")
    app.state.store = AdminStore()
    return TestClient(app)


@pytest.fixture
def authorized_client(client: TestClient) -> TestClient:
    response = client.post(
        "/admin/api/login",
        json={"email": "admin@example.ch", "password": "CorrectHorse!1"},
    )
    assert response.status_code == 200
    return client


def test_admin_endpoints_require_authentication(client: TestClient) -> None:
    assert client.get("/admin/api/me").status_code == 401
    assert client.get("/admin/api/metrics").status_code == 401


def test_login_uses_an_http_only_session_and_rejects_bad_credentials(client: TestClient) -> None:
    rejected = client.post(
        "/admin/api/login", json={"email": "admin@example.ch", "password": "incorrect"}
    )
    assert rejected.status_code == 401
    accepted = client.post(
        "/admin/api/login",
        json={"email": "ADMIN@example.ch", "password": "CorrectHorse!1"},
    )
    assert accepted.status_code == 200
    cookie = accepted.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "Path=/admin" in cookie
    assert client.get("/admin/api/me").json()["principal"] == "admin@example.ch"


def test_logout_revokes_the_session(authorized_client: TestClient) -> None:
    assert authorized_client.post("/admin/api/logout").status_code == 200
    assert authorized_client.get("/admin/api/me").status_code == 401


def test_metrics_are_aggregated_through_by_day_queries(authorized_client: TestClient) -> None:
    response = authorized_client.get("/admin/api/metrics?from=2026-08-18&to=2026-08-19")
    assert response.status_code == 200
    body = response.json()
    assert body["totals"]["messages"] == 2
    assert body["totals"]["conversations"] == 2
    assert body["totals"]["onboarding"] == 3
    assert body["totals"]["average_latency_ms"] == 500
    assert body["breakdowns"]["user_groups"] == {"research_education": 2, "unknown": 1}
    assert body["breakdowns"]["geodata_experience"] == {"advanced": 2, "new": 1}
    assert body["breakdowns"]["intended_uses"] == {"find_data": 2, "unknown": 1}


def test_records_hide_ttl_and_reject_long_or_future_ranges(
    authorized_client: TestClient,
) -> None:
    response = authorized_client.get("/admin/api/records/profiles?from=2026-08-19&to=2026-08-19")
    assert response.status_code == 200
    profiles = response.json()["items"]
    assert len(profiles) == 1
    assert {
        "user_group": profiles[0]["user_group"],
        "geodata_experience": profiles[0]["geodata_experience"],
        "intended_use": profiles[0]["intended_use"],
        "consent_version": profiles[0]["consent_version"],
    } == {
        "user_group": "research_education",
        "geodata_experience": "advanced",
        "intended_use": "find_data",
        "consent_version": "v2",
    }
    assert "expires_at" not in profiles[0]
    assert (
        authorized_client.get("/admin/api/metrics?from=2026-01-01&to=2026-08-19").status_code == 400
    )
    assert (
        authorized_client.get("/admin/api/metrics?from=2099-01-01&to=2099-01-01").status_code == 400
    )


def test_submission_pagination_returns_complete_forms_as_single_records(
    authorized_client: TestClient,
) -> None:
    authorized_client.app.state.store = MixedSubmissionStore()
    query = "?from=2026-08-19&to=2026-08-19&limit=2"

    profiles = authorized_client.get(f"/admin/api/records/profiles{query}").json()
    assert [item["id"] for item in profiles["items"]] == ["p1", "p2"]
    assert profiles["next_cursor"] is None
    assert all(
        {
            "user_group",
            "geodata_experience",
            "intended_use",
            "consent_version",
        }
        <= item.keys()
        for item in profiles["items"]
    )

    feedback = authorized_client.get(f"/admin/api/records/feedback{query}").json()
    assert [item["id"] for item in feedback["items"]] == ["f1", "f2"]
    final_feedback_page = authorized_client.get(
        f"/admin/api/records/feedback{query}&cursor={feedback['next_cursor']}"
    ).json()
    assert final_feedback_page == {"items": [], "next_cursor": None}


def test_conversation_records_group_and_page_whole_ordered_threads(
    authorized_client: TestClient,
) -> None:
    authorized_client.app.state.store = GroupedConversationStore()
    first_page = authorized_client.get(
        "/admin/api/records/conversations?from=2026-08-19&to=2026-08-19&limit=1"
    )
    assert first_page.status_code == 200
    first_body = first_page.json()
    assert len(first_body["items"]) == 1
    conversation = first_body["items"][0]
    assert conversation["conversation_id"] == "c1"
    assert conversation["first_user_message"] == "Show me Basel"
    assert conversation["message_count"] == 2
    assert conversation["models"] == ["test-model"]
    assert conversation["tools_used"] == ["search_locations", "display_layer"]
    assert conversation["total_latency_ms"] == 2000
    assert conversation["input_tokens"] == 300
    assert conversation["output_tokens"] == 80
    assert conversation["layer_count"] == 2
    assert conversation["error_count"] == 0
    assert [turn["message_id"] for turn in conversation["turns"]] == ["m1", "m2"]
    assert all("expires_at" not in turn and "turn" not in turn for turn in conversation["turns"])

    second_page = authorized_client.get(
        "/admin/api/records/conversations?from=2026-08-19&to=2026-08-19&limit=1"
        f"&cursor={first_body['next_cursor']}"
    )
    assert second_page.status_code == 200
    assert second_page.json()["items"][0]["conversation_id"] == "c2"
    assert second_page.json()["next_cursor"] is None
    assert (
        authorized_client.get(
            "/admin/api/records/conversations?from=2026-08-19&to=2026-08-19&cursor=bad"
        ).status_code
        == 400
    )


def test_cors_allows_only_the_configured_local_origin(client: TestClient) -> None:
    response = client.options("/admin/api/metrics", headers={"origin": "http://127.0.0.1:5173"})
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5173"
    rejected = client.options("/admin/api/metrics", headers={"origin": "https://evil.test"})
    assert "access-control-allow-origin" not in rejected.headers


def test_admins_can_list_and_create_local_users(authorized_client: TestClient) -> None:
    listed = authorized_client.get("/admin/api/users")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["email"] == "admin@example.ch"

    created = authorized_client.post(
        "/admin/api/users",
        json={"email": "NEW@example.ch", "password": "AnotherPass!2"},
    )
    assert created.status_code == 201
    assert created.json() == {"email": "new@example.ch", "created": True}
    duplicate = authorized_client.post(
        "/admin/api/users",
        json={"email": "new@example.ch", "password": "AnotherPass!2"},
    )
    assert duplicate.status_code == 409

    authorized_client.post("/admin/api/logout")
    assert (
        authorized_client.post(
            "/admin/api/login",
            json={"email": "new@example.ch", "password": "AnotherPass!2"},
        ).status_code
        == 200
    )


def test_invites_validate_email(authorized_client: TestClient) -> None:
    assert (
        authorized_client.post(
            "/admin/api/users", json={"email": "not-an-email", "password": "AnotherPass!2"}
        ).status_code
        == 400
    )
    assert (
        authorized_client.post(
            "/admin/api/users", json={"email": "valid@example.ch", "password": "short"}
        ).status_code
        == 400
    )
