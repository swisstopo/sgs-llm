from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from botocore.exceptions import ClientError
from botocore.stub import Stubber

from app.admin_dynamo import DynamoAdminUserStore
from app.admin_users import UserAlreadyExistsError


def test_account_and_session_survive_instance_replacement(dynamo_admin_table: Any) -> None:
    old = DynamoAdminUserStore("test-admin-users")
    user = old.create_user(" Admin@Example.ch ", "CorrectHorse!1")
    token = old.create_session(user.email, hours=8)
    replacement = DynamoAdminUserStore("test-admin-users")
    assert replacement.authenticate("ADMIN@example.ch", "CorrectHorse!1") == user
    assert replacement.authenticate(user.email, "wrong-password") is None
    assert replacement.authenticate("missing@example.ch", "CorrectHorse!1") is None
    assert replacement.session_user(token) == user
    replacement.delete_session(token)
    assert old.session_user(token) is None
    assert replacement.list_users() == [user]
    raw = repr(dynamo_admin_table.scan(TableName="test-admin-users")["Items"])
    assert "CorrectHorse!1" not in raw
    assert token not in raw


def test_concurrent_account_creation_cannot_overwrite_password(dynamo_admin_table: Any) -> None:
    stores = [DynamoAdminUserStore("test-admin-users") for _ in range(2)]
    for store in stores:
        store.list_users()

    def create(store: DynamoAdminUserStore) -> str:
        try:
            store.create_user("admin@example.ch", "CorrectHorse!1")
            return "created"
        except UserAlreadyExistsError:
            return "duplicate"

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(create, stores)) == ["created", "duplicate"]
    with pytest.raises(UserAlreadyExistsError):
        stores[1].create_user("ADMIN@example.ch", "DifferentPassword!2")
    assert stores[0].authenticate("admin@example.ch", "CorrectHorse!1") is not None


def test_expired_and_disabled_sessions_fail_before_ttl_cleanup(dynamo_admin_table: Any) -> None:
    store = DynamoAdminUserStore("test-admin-users")
    store.create_user("admin@example.ch", "CorrectHorse!1")
    expired = store.create_session("admin@example.ch", hours=-1)
    assert store.session_user(expired) is None
    assert dynamo_admin_table.get_item(
        TableName="test-admin-users",
        Key={
            "pk": {"S": "SESSION#" + hashlib.sha256(expired.encode()).hexdigest()},
            "sk": {"S": "SESSION"},
        },
    ).get("Item")
    active = store.create_session("admin@example.ch", hours=8)
    dynamo_admin_table.update_item(
        TableName="test-admin-users",
        Key={"pk": {"S": "USERS"}, "sk": {"S": "admin@example.ch"}},
        UpdateExpression="SET enabled = :disabled",
        ExpressionAttributeValues={":disabled": {"BOOL": False}},
    )
    assert store.session_user(active) is None
    assert store.authenticate("admin@example.ch", "CorrectHorse!1") is None
    assert store.session_user("") is None
    assert store.session_user("unknown") is None
    with pytest.raises(ValueError):
        store.create_session("admin@example.ch", hours=8)


def test_storage_errors_do_not_fall_back_to_a_local_account(dynamo_admin_table: Any) -> None:
    store = DynamoAdminUserStore("test-admin-users")
    with Stubber(store._client) as stub:
        stub.add_client_error("get_item", service_error_code="AccessDeniedException")
        with pytest.raises(ClientError):
            store.authenticate("admin@example.ch", "CorrectHorse!1")


def test_sqlite_migration_preserves_credentials_and_active_sessions(
    dynamo_admin_table: Any, tmp_path: Any
) -> None:
    from app.admin_users import AdminUserStore
    from migrate_admin import migrate_admin_database

    source = AdminUserStore(str(tmp_path / "source.sqlite3"))
    source.initialize()
    user = source.create_user("admin@example.ch", "CorrectHorse!1")
    active = source.create_session(user.email, hours=8)
    expired = source.create_session(user.email, hours=-1)
    counts = migrate_admin_database(source.path, "test-admin-users", dynamo_admin_table)
    assert counts == {"users": 1, "sessions": 1}
    target = DynamoAdminUserStore("test-admin-users")
    assert target.authenticate(user.email, "CorrectHorse!1") == user
    assert target.session_user(active) == user
    assert target.session_user(expired) is None
    assert migrate_admin_database(source.path, "test-admin-users", dynamo_admin_table) == counts


def test_migration_does_not_replace_an_existing_different_password(
    dynamo_admin_table: Any, tmp_path: Any
) -> None:
    from app.admin_users import AdminUserStore
    from migrate_admin import migrate_admin_database

    target = DynamoAdminUserStore("test-admin-users")
    target.create_user("admin@example.ch", "ExistingPassword!1")
    source = AdminUserStore(str(tmp_path / "source.sqlite3"))
    source.initialize()
    source.create_user("admin@example.ch", "DifferentPassword!2")
    with pytest.raises(ValueError, match="different record"):
        migrate_admin_database(source.path, "test-admin-users", dynamo_admin_table)
    assert target.authenticate("admin@example.ch", "ExistingPassword!1") is not None


def test_production_setting_selects_dynamodb_without_creating_sqlite(
    dynamo_admin_table: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    from fastapi.testclient import TestClient

    from app import main
    from app.config import Settings

    local_db = tmp_path / "must-not-be-created.sqlite3"
    monkeypatch.setattr(
        main,
        "get_settings",
        lambda: Settings(admin_user_table="test-admin-users", admin_user_db_path=str(local_db)),
    )
    with TestClient(main.app) as client:
        assert client.get("/health").status_code == 200
        assert isinstance(main.app.state.admin_users, DynamoAdminUserStore)
        assert not local_db.exists()
