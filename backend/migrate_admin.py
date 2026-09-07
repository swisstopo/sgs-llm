"""Copy a SQLite admin snapshot into DynamoDB before switching the serving backend.

Preserves password hashes and unexpired sessions; refuses to overwrite different
existing records. Keep the source backup private and do not rerun after cutover.
"""

from __future__ import annotations

import argparse
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from botocore.exceptions import ClientError


def migrate_admin_database(path: Path, table: str, client: Any) -> dict[str, int]:
    with (
        closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as source,
        closing(sqlite3.connect(":memory:")) as snapshot,
    ):
        source.backup(snapshot)
        if snapshot.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("Source database failed its integrity check")
        items = []
        for email, salt, password_hash, enabled, created_at in snapshot.execute(
            "SELECT email,password_salt,password_hash,enabled,created_at FROM admin_users"
        ):
            items.append(
                {
                    "pk": {"S": "USERS"},
                    "sk": {"S": email},
                    "password_salt": {"B": salt},
                    "password_hash": {"B": password_hash},
                    "enabled": {"BOOL": bool(enabled)},
                    "created_at": {"S": created_at},
                }
            )
        users = len(items)
        for token_hash, email, expiry in snapshot.execute(
            "SELECT token_hash,email,expires_at FROM admin_sessions"
        ):
            expires = int(datetime.fromisoformat(expiry).timestamp())
            if expires <= datetime.now(UTC).timestamp():
                continue
            items.append(
                {
                    "pk": {"S": "SESSION#" + token_hash.hex()},
                    "sk": {"S": "SESSION"},
                    "email": {"S": email},
                    "expires_at": {"N": str(expires)},
                }
            )
    for item in items:
        try:
            client.put_item(
                TableName=table, Item=item, ConditionExpression="attribute_not_exists(pk)"
            )
        except ClientError as error:
            if error.response["Error"]["Code"] != "ConditionalCheckFailedException":
                raise
            existing = client.get_item(
                TableName=table, Key={k: item[k] for k in ("pk", "sk")}, ConsistentRead=True
            ).get("Item")
            if existing != item:
                raise ValueError("Destination has a different record; migration stopped") from error
    return {"users": users, "sessions": len(items) - users}


def main() -> None:
    import boto3

    from app.store.dynamo import _credential_options

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--table", required=True)
    parser.add_argument("--region", default="eu-central-1")
    args = parser.parse_args()
    client = boto3.client("dynamodb", region_name=args.region, **_credential_options())
    counts = migrate_admin_database(args.db, args.table, client)
    print(f"Verified {counts['users']} users and {counts['sessions']} unexpired sessions")


if __name__ == "__main__":
    main()
