"""POST /feedback - the feedback form endpoint.

Status codes, CORS behavior and the accepted payload match
mock-agent/server.mjs and frontend/src/feedback/submitFeedback.ts, so switching the
frontend from the mock to this backend needs no frontend change.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Request, Response

from .config import get_settings
from .protocol import coerce_lang
from .security import key_matches
from .store.dynamo import Store

logger = logging.getLogger(__name__)

CATEGORIES = frozenset({"bug", "feature", "improvement", "question", "other"})

MAX_BODY_BYTES = 32_768
MAX_MESSAGE_CHARS = 8_000
MAX_EMAIL_CHARS = 320

CORS_HEADERS = {
    "access-control-allow-origin": "*",
    "access-control-allow-methods": "POST, OPTIONS",
    "access-control-allow-headers": "content-type, x-api-key",
}

router = APIRouter()


def _store(request: Request) -> Store:
    store: Store = request.app.state.store
    return store


def _validate(data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    category = data.get("category")
    message = data.get("message")
    if category not in CATEGORIES:
        return None
    if not isinstance(message, str) or not message.strip():
        return None

    lang = data.get("lang")
    email = data.get("email")
    if email is not None and not isinstance(email, str):
        return None

    return {
        "category": category,
        "message": message.strip()[:MAX_MESSAGE_CHARS],
        "lang": coerce_lang(lang),
        "email": (
            email.strip()[:MAX_EMAIL_CHARS] if isinstance(email, str) and email.strip() else None
        ),
    }


@router.options("/feedback")
async def feedback_preflight() -> Response:
    return Response(status_code=204, headers=CORS_HEADERS)


@router.post("/feedback")
async def submit_feedback(request: Request) -> Response:
    settings = get_settings()

    if not key_matches(settings.api_key, request.headers.get("x-api-key")):
        return Response(status_code=401, headers=CORS_HEADERS)

    raw = await request.body()
    if len(raw) > MAX_BODY_BYTES:
        return Response(status_code=413, headers=CORS_HEADERS)

    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return Response(status_code=400, headers=CORS_HEADERS)

    entry = _validate(data)
    if entry is None:
        return Response(status_code=400, headers=CORS_HEADERS)

    # Not surfaced to the user: the submission succeeded regardless of whether the
    # evaluation table accepted it. The store logs its own failures.
    try:
        await _store(request).record_feedback(**entry)
    except Exception:
        logger.warning("failed to persist feedback (%s)", entry["category"], exc_info=True)

    logger.info("feedback (%s) received", entry["category"])
    return Response(status_code=204, headers=CORS_HEADERS)
