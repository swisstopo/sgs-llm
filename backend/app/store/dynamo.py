"""Persistence for feedback and conversation turns.

Writes exactly the schema documented in docs/deployment.md#what-gets-stored - note
`log_date` rather than `day`, because DAY is a DynamoDB reserved word.

Both writers are best effort: failures are logged and swallowed, so a storage outage does
not cost a user their answer. Unset table names disable persistence, which is how the
image boots with no AWS.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from ..config import Settings

logger = logging.getLogger(__name__)


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(moment: datetime) -> str:
    return moment.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _expires_at(moment: datetime, days: int) -> int:
    return int(moment.timestamp()) + days * 86_400


class Store:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._tables: dict[str, Any] = {}

    def _table(self, name: str) -> Any | None:
        """Resolves a Table lazily. Import and client construction are deferred so
        nothing at startup needs credentials or network."""
        if not name:
            return None
        if name not in self._tables:
            try:
                import boto3
                from botocore.config import Config

                # Without explicit timeouts a throttled table holds a turn task, and with
                # it a per-IP connection slot, for botocore's 60 s x 3 default.
                self._tables[name] = boto3.resource(
                    "dynamodb",
                    config=Config(
                        connect_timeout=5,
                        read_timeout=10,
                        retries={"max_attempts": 2, "mode": "standard"},
                    ),
                ).Table(name)
            except Exception:
                logger.warning("dynamodb unavailable; not persisting to %s", name, exc_info=True)
                self._tables[name] = None
        return self._tables[name]

    async def _put(self, table_name: str, item: dict[str, Any]) -> bool:
        table = self._table(table_name)
        if table is None:
            return False
        try:
            await asyncio.to_thread(table.put_item, Item=item)
            return True
        except Exception:
            logger.warning("failed to write to %s", table_name, exc_info=True)
            return False

    async def record_feedback(
        self,
        *,
        category: str,
        message: str,
        lang: str,
        email: str | None = None,
    ) -> str:
        """Stores one submitted feedback form. Returns the generated id."""
        moment = _now()
        entry_id = str(uuid.uuid4())
        item: dict[str, Any] = {
            "id": entry_id,
            "log_date": moment.strftime("%Y-%m-%d"),
            "ts": _iso(moment),
            "category": category,
            "message": message,
            "lang": lang,
        }
        # No expires_at while retention is switched off (TTL_DAYS=0): TTL skips
        # items without the attribute, so re-enabling deletion later can never
        # reap data written during the keep-everything phase. `ts` remains the
        # record of when the item was stored.
        if self._settings.feedback_ttl_days > 0:
            item["expires_at"] = _expires_at(moment, self._settings.feedback_ttl_days)
        if email:
            item["email"] = email
        await self._put(self._settings.feedback_table, item)
        return entry_id

    async def record_turn(
        self,
        *,
        conversation_id: str,
        message_id: str,
        lang: str,
        user_message: str,
        assistant_markdown: str = "",
        model_id: str = "",
        tool_calls: list[str] | None = None,
        layer_count: int = 0,
        latency_ms: int = 0,
        input_tokens: int = 0,
        output_tokens: int = 0,
        error_code: str | None = None,
    ) -> None:
        """Stores one conversation turn, successful or failed.

        `turn` sorts as "<iso-timestamp>#<message_id>" so a single Query returns a
        conversation in order.
        """
        moment = _now()
        stamp = _iso(moment)
        item: dict[str, Any] = {
            "conversation_id": conversation_id,
            "turn": f"{stamp}#{message_id}",
            "log_date": moment.strftime("%Y-%m-%d"),
            "ts": stamp,
            "message_id": message_id,
            "lang": lang,
            "user_message": user_message,
            "layer_count": layer_count,
            "latency_ms": latency_ms,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
        }
        # Same keep-everything rule as record_feedback: no expires_at at TTL_DAYS=0.
        if self._settings.conversation_ttl_days > 0:
            item["expires_at"] = _expires_at(moment, self._settings.conversation_ttl_days)
        if assistant_markdown:
            item["assistant_markdown"] = assistant_markdown
        if model_id:
            item["model_id"] = model_id
        if tool_calls:
            item["tool_calls"] = tool_calls
        if error_code:
            item["error_code"] = error_code
        await self._put(self._settings.conversation_table, item)
