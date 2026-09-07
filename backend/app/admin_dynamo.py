"""Shared administrator identities for rolling deployments without a filesystem."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from datetime import UTC, datetime, timedelta
from functools import cached_property
from typing import Any, cast

from botocore.exceptions import ClientError

from .admin_users import (
    SALT_BYTES,
    AdminUser,
    UserAlreadyExistsError,
    derive_password,
)
from .store.dynamo import _credential_options


class DynamoAdminUserStore:
    """Passwords and revocable sessions in one on-demand DynamoDB table.

    Users share a partition for listing; each session has its own partition keyed
    by its token fingerprint. Reads are strongly consistent so a login or logout
    takes effect immediately across both tasks during a rolling deployment.
    """

    def __init__(self, table_name: str) -> None:
        self.table_name = table_name

    def initialize(self) -> None:
        """CloudFormation owns the table; startup requires no AWS calls."""

    @cached_property
    def _client(self) -> Any:
        import boto3
        from botocore.config import Config

        return boto3.client(
            "dynamodb",
            region_name=os.environ.get("AWS_REGION", "eu-central-1"),
            **_credential_options(),
            config=Config(
                connect_timeout=3,
                read_timeout=5,
                retries={"max_attempts": 2, "mode": "standard"},
            ),
        )

    @staticmethod
    def _user_key(email: str) -> dict[str, dict[str, str]]:
        return {"pk": {"S": "USERS"}, "sk": {"S": email.strip().lower()}}

    @staticmethod
    def _session_key(token: str) -> dict[str, dict[str, str]]:
        fingerprint = hashlib.sha256(token.encode()).hexdigest()
        return {"pk": {"S": f"SESSION#{fingerprint}"}, "sk": {"S": "SESSION"}}

    def _get(self, key: dict[str, dict[str, str]]) -> dict[str, Any] | None:
        response = self._client.get_item(TableName=self.table_name, Key=key, ConsistentRead=True)
        return cast(dict[str, Any] | None, response.get("Item"))

    @staticmethod
    def _user(item: dict[str, Any]) -> AdminUser:
        return AdminUser(
            email=item["sk"]["S"],
            enabled=item["enabled"]["BOOL"],
            created_at=item["created_at"]["S"],
        )

    def create_user(self, email: str, password: str) -> AdminUser:
        normalized = email.strip().lower()
        salt = secrets.token_bytes(SALT_BYTES)
        item = {
            **self._user_key(normalized),
            "password_salt": {"B": salt},
            "password_hash": {"B": derive_password(password, salt)},
            "enabled": {"BOOL": True},
            "created_at": {"S": datetime.now(UTC).isoformat()},
        }
        try:
            self._client.put_item(
                TableName=self.table_name,
                Item=item,
                ConditionExpression="attribute_not_exists(pk)",
            )
        except ClientError as error:
            if error.response["Error"]["Code"] == "ConditionalCheckFailedException":
                raise UserAlreadyExistsError(normalized) from error
            raise
        return self._user(item)

    def list_users(self) -> list[AdminUser]:
        result: list[AdminUser] = []
        cursor = None
        while True:
            args: dict[str, Any] = {
                "TableName": self.table_name,
                "KeyConditionExpression": "pk = :users",
                "ExpressionAttributeValues": {":users": {"S": "USERS"}},
                "ProjectionExpression": "sk, enabled, created_at",
                "ConsistentRead": True,
            }
            if cursor:
                args["ExclusiveStartKey"] = cursor
            response = self._client.query(**args)
            result.extend(self._user(item) for item in response.get("Items", []))
            cursor = response.get("LastEvaluatedKey")
            if not cursor:
                return sorted(result, key=lambda user: user.created_at)

    def authenticate(self, email: str, password: str) -> AdminUser | None:
        item = self._get(self._user_key(email))
        if item is None or not item["enabled"]["BOOL"]:
            derive_password(password, bytes(SALT_BYTES))
            return None
        actual = derive_password(password, item["password_salt"]["B"])
        if not hmac.compare_digest(actual, item["password_hash"]["B"]):
            return None
        return self._user(item)

    def create_session(self, email: str, *, hours: int) -> str:
        item = self._get(self._user_key(email))
        if item is None or not item["enabled"]["BOOL"]:
            raise ValueError("Cannot create a session for an unavailable administrator")
        token = secrets.token_urlsafe(32)
        expires = int((datetime.now(UTC) + timedelta(hours=hours)).timestamp())
        self._client.put_item(
            TableName=self.table_name,
            Item={
                **self._session_key(token),
                "email": {"S": item["sk"]["S"]},
                "expires_at": {"N": str(expires)},
            },
            ConditionExpression="attribute_not_exists(pk)",
        )
        return token

    def session_user(self, token: str) -> AdminUser | None:
        if not token:
            return None
        session = self._get(self._session_key(token))
        # TTL deletion is asynchronous; never rely on deletion to enforce expiry.
        if session is None or int(session["expires_at"]["N"]) <= datetime.now(UTC).timestamp():
            return None
        item = self._get(self._user_key(session["email"]["S"]))
        return self._user(item) if item is not None and item["enabled"]["BOOL"] else None

    def delete_session(self, token: str) -> None:
        if token:
            self._client.delete_item(TableName=self.table_name, Key=self._session_key(token))
