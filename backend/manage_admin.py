"""Create an administrator in the local SGS LLM user database."""

from __future__ import annotations

import argparse
import getpass
import sys

from app.admin import EMAIL_PATTERN, MAX_PASSWORD_LENGTH, MIN_PASSWORD_LENGTH
from app.admin_dynamo import DynamoAdminUserStore
from app.admin_users import AdminIdentityStore, AdminUserStore, UserAlreadyExistsError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("email", help="Administrator email address")
    storage = parser.add_mutually_exclusive_group()
    storage.add_argument("--db", default="./admin-users.sqlite3", help="Local SQLite database path")
    storage.add_argument("--table", help="Production DynamoDB admin table")
    args = parser.parse_args()
    email = args.email.strip().lower()
    if not EMAIL_PATTERN.fullmatch(email):
        parser.error("email must be a valid address")
    password = getpass.getpass("Password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        print("Passwords do not match.", file=sys.stderr)
        return 2
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        print(
            f"Password must contain between {MIN_PASSWORD_LENGTH} and "
            f"{MAX_PASSWORD_LENGTH} characters.",
            file=sys.stderr,
        )
        return 2
    users: AdminIdentityStore = (
        DynamoAdminUserStore(args.table) if args.table else AdminUserStore(args.db)
    )
    users.initialize()
    try:
        users.create_user(email, password)
    except UserAlreadyExistsError:
        print(f"Administrator already exists: {email}", file=sys.stderr)
        return 1
    print(f"Administrator created: {email}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
