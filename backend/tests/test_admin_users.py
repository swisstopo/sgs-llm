from __future__ import annotations

from pathlib import Path

import pytest

from app.admin_users import AdminUserStore, UserAlreadyExistsError


def test_passwords_and_session_tokens_are_never_stored_verbatim(tmp_path: Path) -> None:
    database = tmp_path / "admins.sqlite3"
    users = AdminUserStore(str(database))
    users.initialize()
    users.create_user("Admin@Example.ch", "CorrectHorse!1")

    assert users.authenticate("admin@example.ch", "CorrectHorse!1") is not None
    assert users.authenticate("admin@example.ch", "wrong-password") is None
    assert users.authenticate("missing@example.ch", "CorrectHorse!1") is None

    session = users.create_session("admin@example.ch", hours=8)
    contents = database.read_bytes()
    assert b"CorrectHorse!1" not in contents
    assert session.encode() not in contents
    assert users.session_user(session) is not None

    users.delete_session(session)
    assert users.session_user(session) is None


def test_users_are_normalized_listed_and_unique(tmp_path: Path) -> None:
    users = AdminUserStore(str(tmp_path / "admins.sqlite3"))
    users.initialize()
    created = users.create_user(" Admin@Example.ch ", "CorrectHorse!1")
    assert created.email == "admin@example.ch"
    assert users.list_users() == [created]

    with pytest.raises(UserAlreadyExistsError):
        users.create_user("ADMIN@example.ch", "AnotherPass!2")
