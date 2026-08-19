"""Small, local administrator identity store.

Passwords never enter the database directly.  Each password is independently salted
and derived with scrypt.  Browser sessions use random bearer values while only their
SHA-256 fingerprints are stored, so a copied database does not contain usable session
cookies either.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
HASH_BYTES = 64
SALT_BYTES = 16


@dataclass(frozen=True)
class AdminUser:
    email: str
    enabled: bool
    created_at: str


class UserAlreadyExistsError(Exception):
    """Raised when an administrator email is already registered."""


class AdminUserStore:
    """SQLite-backed users and revocable sessions for the small admin audience."""

    def __init__(self, path: str) -> None:
        self.path = Path(path).expanduser().resolve()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS admin_users (
                    email TEXT PRIMARY KEY,
                    password_salt BLOB NOT NULL,
                    password_hash BLOB NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS admin_sessions (
                    token_hash BLOB PRIMARY KEY,
                    email TEXT NOT NULL REFERENCES admin_users(email) ON DELETE CASCADE,
                    expires_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS admin_sessions_expiry
                    ON admin_sessions(expires_at);
                """
            )

    def create_user(self, email: str, password: str) -> AdminUser:
        normalized = email.strip().lower()
        salt = secrets.token_bytes(SALT_BYTES)
        password_hash = self._derive(password, salt)
        created_at = datetime.now(UTC).isoformat()
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO admin_users
                        (email, password_salt, password_hash, enabled, created_at)
                    VALUES (?, ?, ?, 1, ?)
                    """,
                    (normalized, salt, password_hash, created_at),
                )
        except sqlite3.IntegrityError as error:
            raise UserAlreadyExistsError(normalized) from error
        return AdminUser(email=normalized, enabled=True, created_at=created_at)

    def list_users(self) -> list[AdminUser]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT email, enabled, created_at FROM admin_users ORDER BY created_at"
            ).fetchall()
        return [
            AdminUser(
                email=row["email"], enabled=bool(row["enabled"]), created_at=row["created_at"]
            )
            for row in rows
        ]

    def authenticate(self, email: str, password: str) -> AdminUser | None:
        normalized = email.strip().lower()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT email, password_salt, password_hash, enabled, created_at
                FROM admin_users WHERE email = ?
                """,
                (normalized,),
            ).fetchone()
        if row is None or not row["enabled"]:
            # Do equivalent expensive work for unknown users to reduce account probing.
            self._derive(password, bytes(SALT_BYTES))
            return None
        actual = self._derive(password, row["password_salt"])
        if not hmac.compare_digest(actual, row["password_hash"]):
            return None
        return AdminUser(email=row["email"], enabled=True, created_at=row["created_at"])

    def create_session(self, email: str, *, hours: int) -> str:
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).digest()
        expires_at = (datetime.now(UTC) + timedelta(hours=hours)).isoformat()
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM admin_sessions WHERE expires_at <= ?",
                (datetime.now(UTC).isoformat(),),
            )
            connection.execute(
                "INSERT INTO admin_sessions (token_hash, email, expires_at) VALUES (?, ?, ?)",
                (token_hash, email, expires_at),
            )
        return token

    def session_user(self, token: str) -> AdminUser | None:
        if not token:
            return None
        token_hash = hashlib.sha256(token.encode()).digest()
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT u.email, u.enabled, u.created_at, s.expires_at
                FROM admin_sessions s
                JOIN admin_users u ON u.email = s.email
                WHERE s.token_hash = ?
                """,
                (token_hash,),
            ).fetchone()
            if row is None or row["expires_at"] <= datetime.now(UTC).isoformat():
                connection.execute("DELETE FROM admin_sessions WHERE token_hash = ?", (token_hash,))
                return None
        if not row["enabled"]:
            return None
        return AdminUser(email=row["email"], enabled=True, created_at=row["created_at"])

    def delete_session(self, token: str) -> None:
        if not token:
            return
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM admin_sessions WHERE token_hash = ?",
                (hashlib.sha256(token.encode()).digest(),),
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    @staticmethod
    def _derive(password: str, salt: bytes) -> bytes:
        return hashlib.scrypt(
            password.encode(),
            salt=salt,
            n=SCRYPT_N,
            r=SCRYPT_R,
            p=SCRYPT_P,
            dklen=HASH_BYTES,
        )
