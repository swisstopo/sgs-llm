"""What lands in DynamoDB and S3.

The item shapes are a contract with docs/deployment.md#what-gets-stored and with
scripts/read-db.sh, which is how anyone inspects the pilot's data.
"""

from __future__ import annotations

import json
from typing import Any

from app.config import Settings
from app.store.artifacts import ArtifactStore
from app.store.dynamo import Store, _credential_options


class FakeTable:
    def __init__(self, fail: bool = False) -> None:
        self.items: list[dict[str, Any]] = []
        self._fail = fail

    def put_item(self, Item: dict[str, Any]) -> None:
        if self._fail:
            raise RuntimeError("ProvisionedThroughputExceededException")
        self.items.append(Item)

    def query(self, **kwargs: Any) -> dict[str, Any]:
        return {"Items": self.items, "LastEvaluatedKey": None}


def _store(settings: Settings, tables: dict[str, FakeTable]) -> Store:
    store = Store(settings)
    store._tables.update(tables)
    return store


SETTINGS = Settings(
    feedback_table="sgs-llm-feedback",
    conversation_table="sgs-llm-conversations",
    feedback_ttl_days=365,
    conversation_ttl_days=90,
)


def test_local_legacy_aws_access_key_is_passed_explicitly(monkeypatch: Any) -> None:
    monkeypatch.delenv("AWS_ACCESS_KEY_ID", raising=False)
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY", "local-access")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "local-secret")

    assert _credential_options() == {
        "aws_access_key_id": "local-access",
        "aws_secret_access_key": "local-secret",
    }


def test_standard_aws_access_key_takes_precedence(monkeypatch: Any) -> None:
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "standard-access")
    monkeypatch.setenv("AWS_ACCESS_KEY", "legacy-access")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "secret")
    monkeypatch.setenv("AWS_SESSION_TOKEN", "token")

    assert _credential_options() == {
        "aws_access_key_id": "standard-access",
        "aws_secret_access_key": "secret",
        "aws_session_token": "token",
    }


class TestFeedback:
    async def test_writes_the_documented_attributes(self) -> None:
        table = FakeTable()
        store = _store(SETTINGS, {"sgs-llm-feedback": table})

        entry_id = await store.record_feedback(
            category="bug", message="Karte lädt nicht", lang="de", email="a@example.test"
        )

        item = table.items[0]
        assert item["id"] == entry_id
        assert item["category"] == "bug"
        assert item["email"] == "a@example.test"
        # ByDay GSI: log_date, not `day` - DAY is a DynamoDB reserved word.
        assert item["log_date"].count("-") == 2
        assert item["ts"].endswith("Z")
        assert isinstance(item["expires_at"], int)

    async def test_ttl_reflects_the_configured_retention(self) -> None:
        table = FakeTable()
        store = _store(SETTINGS, {"sgs-llm-feedback": table})
        await store.record_feedback(category="other", message="x", lang="de")

        item = table.items[0]
        from datetime import UTC, datetime

        days = (item["expires_at"] - int(datetime.now(UTC).timestamp())) / 86_400
        assert 364 < days <= 365

    async def test_zero_retention_writes_no_expires_at(self) -> None:
        """TTL_DAYS=0 means keep everything: the attribute is omitted entirely, so
        TTL cannot reap these items even if automatic deletion is enabled later."""
        settings = Settings(
            feedback_table="sgs-llm-feedback",
            conversation_table="sgs-llm-conversations",
            feedback_ttl_days=0,
            conversation_ttl_days=0,
        )
        feedback = FakeTable()
        conversations = FakeTable()
        store = _store(
            settings, {"sgs-llm-feedback": feedback, "sgs-llm-conversations": conversations}
        )

        await store.record_feedback(category="bug", message="x", lang="de")
        await store.record_onboarding(
            user_group="private_individual",
            geodata_experience="new",
            intended_use="learning_other",
            consent_version="v2",
            lang="de",
        )
        await store.record_turn(
            conversation_id="c1",
            message_id="m1",
            lang="de",
            user_message="x",
            assistant_markdown="y",
            model_id="m",
            tool_calls=[],
            layer_count=0,
            latency_ms=1,
            input_tokens=1,
            output_tokens=1,
            error_code=None,
        )

        assert "expires_at" not in feedback.items[0]
        assert "expires_at" not in feedback.items[1]
        assert "expires_at" not in conversations.items[0]
        # The write moment stays recorded regardless.
        assert feedback.items[0]["ts"].endswith("Z")
        assert feedback.items[1]["ts"].endswith("Z")
        assert conversations.items[0]["ts"].endswith("Z")

    async def test_an_absent_email_is_not_stored_as_empty(self) -> None:
        table = FakeTable()
        store = _store(SETTINGS, {"sgs-llm-feedback": table})
        await store.record_feedback(category="bug", message="x", lang="de", email=None)
        assert "email" not in table.items[0]

    async def test_a_write_failure_is_swallowed(self) -> None:
        store = _store(SETTINGS, {"sgs-llm-feedback": FakeTable(fail=True)})
        assert await store.record_feedback(category="bug", message="x", lang="de")

    async def test_no_table_configured_disables_persistence(self) -> None:
        """Unset table names disable persistence, so the image boots with no AWS."""
        store = Store(Settings())
        assert await store.record_feedback(category="bug", message="x", lang="de")

    async def test_onboarding_is_distinct_and_requires_a_confirmed_write(self) -> None:
        table = FakeTable()
        store = _store(SETTINGS, {"sgs-llm-feedback": table})

        entry_id = await store.record_onboarding(
            user_group="public_administration",
            geodata_experience="advanced",
            intended_use="professional_analysis",
            consent_version="v2",
            lang="de",
        )

        assert entry_id == table.items[0]["id"]
        assert table.items[0]["entry_type"] == "onboarding"
        assert "message" not in table.items[0]
        assert "email" not in table.items[0]

        unavailable = Store(Settings())
        assert (
            await unavailable.record_onboarding(
                user_group="private_individual",
                geodata_experience="new",
                intended_use="learning_other",
                consent_version="v2",
                lang="en",
            )
            is None
        )


class TestConversationTurns:
    async def test_turn_key_sorts_a_conversation_in_order(self) -> None:
        table = FakeTable()
        store = _store(SETTINGS, {"sgs-llm-conversations": table})

        for message_id in ("m1", "m2", "m3"):
            await store.record_turn(
                conversation_id="c1",
                message_id=message_id,
                lang="de",
                user_message=f"frage {message_id}",
                assistant_markdown="antwort",
                model_id="mistral.ministral-3-14b-instruct@eu-west-1",
            )

        keys = [item["turn"] for item in table.items]
        assert keys == sorted(keys)
        assert all(key.count("#") == 1 for key in keys)
        assert table.items[0]["turn"].endswith("#m1")

    async def test_records_the_evaluation_fields(self) -> None:
        table = FakeTable()
        store = _store(SETTINGS, {"sgs-llm-conversations": table})

        await store.record_turn(
            conversation_id="c1",
            message_id="m1",
            lang="fr",
            user_message="Où sont les crues?",
            assistant_markdown="## Réponse",
            model_id="eu.anthropic.claude-sonnet-4-6@eu-central-1",
            tool_calls=["search_locations", "filter_features"],
            layer_count=1,
            latency_ms=4210,
            input_tokens=1200,
            output_tokens=300,
        )

        item = table.items[0]
        assert item["tool_calls"] == ["search_locations", "filter_features"]
        assert item["model_id"].startswith("eu.anthropic")
        assert item["latency_ms"] == 4210
        assert item["layer_count"] == 1
        assert "error_code" not in item

    async def test_a_failed_turn_is_recorded_with_its_error(self) -> None:
        table = FakeTable()
        store = _store(SETTINGS, {"sgs-llm-conversations": table})

        await store.record_turn(
            conversation_id="c1",
            message_id="m1",
            lang="de",
            user_message="frage",
            error_code="timeout",
        )
        item = table.items[0]
        assert item["error_code"] == "timeout"
        assert "assistant_markdown" not in item

    async def test_numbers_are_integers_dynamodb_rejects_floats(self) -> None:
        table = FakeTable()
        store = _store(SETTINGS, {"sgs-llm-conversations": table})
        await store.record_turn(
            conversation_id="c1", message_id="m1", lang="de", user_message="x", latency_ms=1234
        )
        item = table.items[0]
        for field in ("latency_ms", "input_tokens", "output_tokens", "layer_count", "expires_at"):
            assert isinstance(item[field], int), field

    async def test_admin_reads_use_the_by_day_index(self) -> None:
        table = FakeTable()
        table.items = [{"latency_ms": 12, "log_date": "2026-08-19"}]
        store = _store(SETTINGS, {"sgs-llm-conversations": table})

        items, cursor = await store.query_day(
            table_name="sgs-llm-conversations", log_date="2026-08-19", limit=50
        )

        assert items == table.items
        assert cursor is None


class TestArtifacts:
    async def test_without_a_bucket_it_serves_from_memory(self) -> None:
        store = ArtifactStore(Settings())
        assert store.uses_bucket is False

        url = await store.publish_geojson(
            "a.geojson", {"type": "FeatureCollection", "features": []}
        )
        # A relative path the caller resolves against the public origin.
        assert url == "/data/a.geojson"

        body = store.read_local("a.geojson")
        assert body is not None
        assert json.loads(body)["type"] == "FeatureCollection"

    async def test_memory_store_is_bounded(self) -> None:
        """A long-running task must not grow without limit when no bucket is set."""
        store = ArtifactStore(Settings())
        for index in range(80):
            await store.publish_geojson(f"{index}.geojson", {"type": "FeatureCollection"})
        assert store.read_local("0.geojson") is None
        assert store.read_local("79.geojson") is not None

    async def test_unicode_survives_the_round_trip(self) -> None:
        store = ArtifactStore(Settings())
        await store.publish_geojson(
            "x.geojson",
            {"type": "FeatureCollection", "features": [{"properties": {"name": "Zürich, Vallée"}}]},
        )
        body = store.read_local("x.geojson")
        assert body is not None
        assert "Zürich" in json.loads(body)["features"][0]["properties"]["name"]

    async def test_with_a_bucket_it_presigns(self) -> None:
        class FakeS3:
            def __init__(self) -> None:
                self.puts: list[dict[str, Any]] = []

            def put_object(self, **kwargs: Any) -> None:
                self.puts.append(kwargs)

            def generate_presigned_url(self, operation: str, Params: Any, ExpiresIn: int) -> str:
                return f"https://bucket.s3.test/{Params['Key']}?X-Amz-Expires={ExpiresIn}"

        settings = Settings(
            data_layer_bucket="sgs-llm-data-259789526488", data_layer_presign_ttl=900
        )
        store = ArtifactStore(settings)
        fake = FakeS3()
        store._s3 = fake
        store._s3_resolved = True

        url = await store.publish_geojson("a.geojson", {"type": "FeatureCollection"})
        assert url is not None
        assert url.startswith("https://bucket.s3.test/a.geojson")
        assert "X-Amz-Expires=900" in url
        assert fake.puts[0]["ContentType"] == "application/geo+json"
        assert fake.puts[0]["Bucket"] == "sgs-llm-data-259789526488"

    async def test_a_publish_failure_returns_none_rather_than_raising(self) -> None:
        class BrokenS3:
            def put_object(self, **kwargs: Any) -> None:
                raise RuntimeError("AccessDenied")

        store = ArtifactStore(Settings(data_layer_bucket="b"))
        store._s3 = BrokenS3()
        store._s3_resolved = True

        assert await store.publish_geojson("a.geojson", {"type": "FeatureCollection"}) is None
