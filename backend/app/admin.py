"""Protected product analytics and content-review API for ``/admin``."""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import logging
import re
from collections import Counter
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any, cast

from fastapi import APIRouter, Request, Response
from fastapi.responses import JSONResponse

from .admin_users import AdminUserStore, UserAlreadyExistsError
from .config import Settings
from .store.dynamo import Store

logger = logging.getLogger("sgs.admin.audit")
router = APIRouter(prefix="/admin/api")
MAX_RANGE_DAYS = 31
MAX_PAGE_SIZE = 200
EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
SESSION_COOKIE = "sgs_admin_session"
MIN_PASSWORD_LENGTH = 10
MAX_PASSWORD_LENGTH = 1024


def _cors(request: Request) -> dict[str, str]:
    origin = request.headers.get("origin", "")
    allowed_origins = request.app.state.settings.origin_allowlist
    headers = {"cache-control": "no-store"}
    if origin and origin in allowed_origins:
        headers.update(
            {
                "access-control-allow-origin": origin,
                "access-control-allow-credentials": "true",
                "vary": "Origin",
            }
        )
    return headers


def _error(request: Request, status: int, detail: str) -> JSONResponse:
    return JSONResponse({"detail": detail}, status_code=status, headers=_cors(request))


def _users(request: Request) -> AdminUserStore:
    return cast(AdminUserStore, request.app.state.admin_users)


async def _principal(request: Request) -> str | None:
    user = await asyncio.to_thread(
        _users(request).session_user, request.cookies.get(SESSION_COOKIE, "")
    )
    return user.email if user else None


def _parse_range(request: Request) -> tuple[date, date] | None:
    today = datetime.now(UTC).date()
    try:
        end = date.fromisoformat(request.query_params.get("to", today.isoformat()))
        start = date.fromisoformat(
            request.query_params.get("from", (end - timedelta(days=6)).isoformat())
        )
    except ValueError:
        return None
    if end < start or (end - start).days >= MAX_RANGE_DAYS or end > today:
        return None
    return start, end


def _days(start: date, end: date) -> list[str]:
    return [(start + timedelta(days=index)).isoformat() for index in range((end - start).days + 1)]


async def _all_for_day(store: Store, table: str, day: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    cursor: dict[str, Any] | None = None
    while True:
        page, cursor = await store.query_day(
            table_name=table, log_date=day, exclusive_start_key=cursor
        )
        items.extend(page)
        if cursor is None:
            return items


def _encode_cursor(day_index: int, key: dict[str, Any] | None) -> str:
    raw = json.dumps({"day": day_index, "key": key}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_cursor(raw: str | None) -> tuple[int, dict[str, Any] | None]:
    if not raw:
        return 0, None
    try:
        padded = raw + "=" * (-len(raw) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded))
        day_index = int(value["day"])
        key = value.get("key")
        return day_index, key if isinstance(key, dict) else None
    except (
        ValueError,
        TypeError,
        KeyError,
        UnicodeDecodeError,
        binascii.Error,
        json.JSONDecodeError,
    ):
        raise ValueError("invalid cursor") from None


def _encode_offset(offset: int) -> str:
    raw = json.dumps({"offset": offset}, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_offset(raw: str | None) -> int:
    if not raw:
        return 0
    try:
        padded = raw + "=" * (-len(raw) % 4)
        value = json.loads(base64.urlsafe_b64decode(padded))
        offset = int(value["offset"])
        if offset < 0:
            raise ValueError
        return offset
    except (
        ValueError,
        TypeError,
        KeyError,
        UnicodeDecodeError,
        binascii.Error,
        json.JSONDecodeError,
    ):
        raise ValueError("invalid cursor") from None


def _total_turn_field(turns: list[dict[str, Any]], field: str) -> int:
    return sum(
        int(value)
        for turn in turns
        if isinstance((value := turn.get(field)), int) and not isinstance(value, bool)
    )


def _group_conversations(turns: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for index, raw_turn in enumerate(turns):
        turn = dict(raw_turn)
        turn.pop("expires_at", None)
        turn.pop("turn", None)
        conversation_id = str(
            turn.get("conversation_id") or turn.get("message_id") or f"unknown-{index}"
        )
        grouped.setdefault(conversation_id, []).append(turn)

    conversations: list[dict[str, Any]] = []
    for conversation_id, conversation_turns in grouped.items():
        conversation_turns.sort(key=lambda turn: str(turn.get("ts", "")))
        first = conversation_turns[0]
        last = conversation_turns[-1]
        models = list(
            dict.fromkeys(
                str(turn["model_id"]) for turn in conversation_turns if turn.get("model_id")
            )
        )
        tools_used = list(
            dict.fromkeys(
                str(tool)
                for turn in conversation_turns
                for tool in turn.get("tool_calls", [])
                if tool
            )
        )

        conversations.append(
            {
                "conversation_id": conversation_id,
                "started_at": first.get("ts", ""),
                "updated_at": last.get("ts", ""),
                "lang": first.get("lang", "unknown"),
                "message_count": len(conversation_turns),
                "first_user_message": first.get("user_message", ""),
                "models": models,
                "tools_used": tools_used,
                "total_latency_ms": _total_turn_field(conversation_turns, "latency_ms"),
                "input_tokens": _total_turn_field(conversation_turns, "input_tokens"),
                "output_tokens": _total_turn_field(conversation_turns, "output_tokens"),
                "layer_count": _total_turn_field(conversation_turns, "layer_count"),
                "error_count": sum(1 for turn in conversation_turns if turn.get("error_code")),
                "turns": conversation_turns,
            }
        )
    conversations.sort(
        key=lambda conversation: str(conversation.get("updated_at", "")), reverse=True
    )
    return conversations


async def _paged(
    store: Store,
    table: str,
    days: list[str],
    limit: int,
    cursor_raw: str | None,
    *,
    accept: Callable[[dict[str, Any]], bool] | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    day_index, key = _decode_cursor(cursor_raw)
    records: list[dict[str, Any]] = []
    while day_index < len(days) and len(records) < limit:
        page, last_key = await store.query_day(
            table_name=table,
            log_date=days[day_index],
            limit=limit - len(records),
            exclusive_start_key=key,
        )
        records.extend(item for item in page if accept is None or accept(item))
        if last_key:
            key = last_key
            if len(records) >= limit:
                return records, _encode_cursor(day_index, key)
            continue
        day_index += 1
        key = None
    return records, _encode_cursor(day_index, None) if day_index < len(days) else None


def _is_profile(item: dict[str, Any]) -> bool:
    return item.get("entry_type") == "onboarding"


def _is_feedback(item: dict[str, Any]) -> bool:
    return not _is_profile(item)


@router.options("/{path:path}")
async def preflight(request: Request) -> Response:
    headers = _cors(request)
    headers.update(
        {
            "access-control-allow-methods": "GET, POST, OPTIONS",
            "access-control-allow-headers": "authorization, content-type",
        }
    )
    return Response(status_code=204, headers=headers)


@router.post("/login")
async def login(request: Request) -> Response:
    try:
        body = await request.json()
    except ValueError:
        return _error(request, 400, "Invalid request")
    email = body.get("email", "").strip().lower() if isinstance(body, dict) else ""
    password = body.get("password", "") if isinstance(body, dict) else ""
    if not isinstance(password, str) or not EMAIL_PATTERN.fullmatch(email):
        return _error(request, 401, "Invalid email or password")
    user = await asyncio.to_thread(_users(request).authenticate, email, password)
    if user is None:
        logger.warning(
            "admin_auth_failed email_fingerprint=%s",
            hashlib.sha256(email.encode()).hexdigest()[:12],
        )
        return _error(request, 401, "Invalid email or password")
    settings: Settings = request.app.state.settings
    token = await asyncio.to_thread(
        _users(request).create_session, user.email, hours=settings.admin_session_hours
    )
    response = JSONResponse(
        {"authenticated": True, "principal": user.email}, headers=_cors(request)
    )
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=settings.admin_session_hours * 3600,
        httponly=True,
        secure=settings.admin_cookie_secure,
        samesite="strict",
        path="/admin",
    )
    logger.info("admin_login principal=%s", user.email)
    return response


@router.post("/logout")
async def logout(request: Request) -> Response:
    token = request.cookies.get(SESSION_COOKIE, "")
    await asyncio.to_thread(_users(request).delete_session, token)
    response = JSONResponse({"authenticated": False}, headers=_cors(request))
    response.delete_cookie(SESSION_COOKIE, path="/admin")
    return response


@router.get("/me")
async def me(request: Request) -> Response:
    principal = await _principal(request)
    if principal is None:
        return _error(request, 401, "Authentication required")
    return JSONResponse({"authenticated": True, "principal": principal}, headers=_cors(request))


@router.get("/users")
async def users(request: Request) -> Response:
    principal = await _principal(request)
    if principal is None:
        return _error(request, 401, "Authentication required")
    try:
        stored_users = await asyncio.to_thread(_users(request).list_users)
    except Exception:
        logger.exception("admin_user_list_failed principal=%s", principal)
        return _error(request, 503, "User management is temporarily unavailable")
    result = [
        {
            "username": user.email,
            "email": user.email,
            "enabled": user.enabled,
            "status": "ACTIVE" if user.enabled else "DISABLED",
            "created_at": user.created_at,
        }
        for user in stored_users
    ]
    logger.info("admin_read principal=%s resource=users count=%d", principal, len(result))
    return JSONResponse({"items": result}, headers=_cors(request))


@router.post("/users")
async def create_user(request: Request) -> Response:
    principal = await _principal(request)
    if principal is None:
        return _error(request, 401, "Authentication required")
    try:
        body = await request.json()
    except ValueError:
        return _error(request, 400, "Invalid request")
    email = body.get("email", "").strip().lower() if isinstance(body, dict) else ""
    password = body.get("password", "") if isinstance(body, dict) else ""
    if len(email) > 320 or not EMAIL_PATTERN.fullmatch(email):
        return _error(request, 400, "A valid email address is required")
    if (
        not isinstance(password, str)
        or len(password) < MIN_PASSWORD_LENGTH
        or len(password) > MAX_PASSWORD_LENGTH
    ):
        return _error(
            request,
            400,
            "Password must contain between "
            f"{MIN_PASSWORD_LENGTH} and {MAX_PASSWORD_LENGTH} characters",
        )
    try:
        await asyncio.to_thread(_users(request).create_user, email, password)
    except UserAlreadyExistsError:
        return _error(request, 409, "An administrator with this email already exists")
    except Exception:
        logger.exception("admin_user_create_failed principal=%s", principal)
        return _error(request, 503, "The administrator could not be created")
    fingerprint = hashlib.sha256(email.encode()).hexdigest()[:12]
    logger.info(
        "admin_user_created principal=%s email_fingerprint=%s",
        principal,
        fingerprint,
    )
    return JSONResponse(
        {"email": email, "created": True},
        status_code=201,
        headers=_cors(request),
    )


@router.get("/metrics")
async def metrics(request: Request) -> Response:
    principal = await _principal(request)
    if principal is None:
        return _error(request, 401, "Authentication required")
    period = _parse_range(request)
    if period is None:
        return _error(
            request, 400, "Date range must be valid, no more than 31 days, and not future"
        )
    start, end = period
    store: Store = request.app.state.store
    daily: list[dict[str, Any]] = []
    languages: Counter[str] = Counter()
    user_groups: Counter[str] = Counter()
    experience: Counter[str] = Counter()
    intended_uses: Counter[str] = Counter()
    models: Counter[str] = Counter()
    errors: Counter[str] = Counter()
    total_latency = 0
    latency_samples = 0
    try:
        day_records = await asyncio.gather(
            *(
                asyncio.gather(
                    _all_for_day(store, request.app.state.settings.conversation_table, day),
                    _all_for_day(store, request.app.state.settings.feedback_table, day),
                )
                for day in _days(start, end)
            )
        )
    except Exception:
        logger.exception("admin_read_failed principal=%s resource=metrics", principal)
        return _error(request, 503, "Analytics storage is temporarily unavailable")
    for day, (turns, submissions) in zip(_days(start, end), day_records, strict=True):
        profiles = [entry for entry in submissions if entry.get("entry_type") == "onboarding"]
        feedback = [entry for entry in submissions if entry.get("entry_type") != "onboarding"]
        for turn in turns:
            languages[str(turn.get("lang", "unknown"))] += 1
            if turn.get("model_id"):
                models[str(turn["model_id"])] += 1
            if turn.get("error_code"):
                errors[str(turn["error_code"])] += 1
            if isinstance(turn.get("latency_ms"), int):
                total_latency += turn["latency_ms"]
                latency_samples += 1
        for profile in profiles:
            user_groups[str(profile.get("user_group", "unknown"))] += 1
            experience[str(profile.get("geodata_experience", "unknown"))] += 1
            intended_uses[str(profile.get("intended_use", "unknown"))] += 1
        daily.append(
            {
                "date": day,
                "messages": len(turns),
                "conversations": len({turn.get("conversation_id") for turn in turns}),
                "onboarding": len(profiles),
                "feedback": len(feedback),
                "errors": sum(1 for turn in turns if turn.get("error_code")),
            }
        )
    totals = {
        key: sum(int(day[key]) for day in daily)
        for key in ("messages", "conversations", "onboarding", "feedback", "errors")
    }
    totals["average_latency_ms"] = round(total_latency / latency_samples) if latency_samples else 0
    logger.info("admin_read principal=%s resource=metrics from=%s to=%s", principal, start, end)
    return JSONResponse(
        {
            "from": start.isoformat(),
            "to": end.isoformat(),
            "daily": daily,
            "totals": totals,
            "breakdowns": {
                "languages": languages,
                "user_groups": user_groups,
                "geodata_experience": experience,
                "intended_uses": intended_uses,
                "models": models,
                "errors": errors,
            },
        },
        headers=_cors(request),
    )


@router.get("/records/{kind}")
async def records(request: Request, kind: str) -> Response:
    principal = await _principal(request)
    if principal is None:
        return _error(request, 401, "Authentication required")
    if kind not in {"conversations", "profiles", "feedback"}:
        return _error(request, 404, "Unknown record type")
    period = _parse_range(request)
    if period is None:
        return _error(request, 400, "Invalid date range")
    try:
        limit = min(MAX_PAGE_SIZE, max(1, int(request.query_params.get("limit", "50"))))
        start, end = period
        newest_days = list(reversed(_days(start, end)))
        settings: Settings = request.app.state.settings
        if kind == "conversations":
            turns_by_day = await asyncio.gather(
                *(
                    _all_for_day(request.app.state.store, settings.conversation_table, day)
                    for day in newest_days
                )
            )
            conversations = _group_conversations(
                [turn for daily_turns in turns_by_day for turn in daily_turns]
            )
            offset = _decode_offset(request.query_params.get("cursor"))
            items = conversations[offset : offset + limit]
            next_offset = offset + len(items)
            cursor = _encode_offset(next_offset) if next_offset < len(conversations) else None
        else:
            accept = _is_profile if kind == "profiles" else _is_feedback
            items, cursor = await _paged(
                request.app.state.store,
                settings.feedback_table,
                newest_days,
                limit,
                request.query_params.get("cursor"),
                accept=accept,
            )
    except (ValueError, TypeError):
        return _error(request, 400, "Invalid pagination")
    except Exception:
        logger.exception("admin_read_failed principal=%s resource=%s", principal, kind)
        return _error(request, 503, "Analytics storage is temporarily unavailable")
    # Do not return retention internals or database pagination keys as content fields.
    for item in items:
        item.pop("expires_at", None)
    logger.info(
        "admin_read principal=%s resource=%s from=%s to=%s count=%d fingerprint=%s",
        principal,
        kind,
        start,
        end,
        len(items),
        hashlib.sha256(principal.encode()).hexdigest()[:12],
    )
    return JSONResponse({"items": items, "next_cursor": cursor}, headers=_cors(request))
