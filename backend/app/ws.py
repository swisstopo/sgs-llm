"""/ws/v1, the protocol v1 WebSocket endpoint.

Owns the exchange lifecycle so the agent loop cannot emit two terminal events: `done` is
sent here for every outcome, including error, cancellation and timeout.

Keepalive is uvicorn's --ws-ping-interval, which holds a quiet chat open under the ALB's
3600 s idle timeout.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from . import i18n
from .agent.loop import TurnStats, run_turn
from .config import get_settings
from .limits import TooManyConnections
from .protocol import (
    Cancel,
    Done,
    Error,
    ProtocolLang,
    ServerEvent,
    UserMessage,
    coerce_lang,
    parse_client_event,
)
from .security import client_key, key_from_subprotocols, key_matches, origin_allowed

logger = logging.getLogger(__name__)

router = APIRouter()

# Close codes: 1008 is "policy violation", which is what a rejected origin, a bad key
# and an over-limit client all are.
CLOSE_POLICY = 1008
CLOSE_GOING_AWAY = 1001


def resolve_base_url(websocket: WebSocket) -> str:
    """The public origin to resolve relative data URLs against.

    CloudFront forwards the viewer Host and adds X-Forwarded-Proto: https, so the
    URLs we emit are same-origin and not blocked as mixed content - the same
    derivation mock-agent does (mock-agent/server.mjs).
    """
    settings = get_settings()
    forwarded_host = websocket.headers.get("x-forwarded-host")
    if forwarded_host:
        proto = websocket.headers.get("x-forwarded-proto", "https")
        return f"{proto}://{forwarded_host}"
    if settings.public_base_url:
        return settings.public_base_url
    host = websocket.headers.get("host")
    return f"http://{host}" if host else ""


class Exchange:
    """One connection's state: the send lock, the conversation id, the live turn."""

    def __init__(self, websocket: WebSocket) -> None:
        self._websocket = websocket
        self._send_lock = asyncio.Lock()
        self.conversation_id = str(uuid.uuid4())
        self.task: asyncio.Task[None] | None = None
        self.active_message_id: str | None = None

    async def send(self, event: ServerEvent) -> None:
        if self._websocket.client_state is not WebSocketState.CONNECTED:
            return
        async with self._send_lock:
            # The peer can vanish mid-exchange. The receive loop handles teardown, so a
            # failed send does not propagate into the agent loop.
            with contextlib.suppress(WebSocketDisconnect, RuntimeError):
                await self._websocket.send_text(event.frame())

    def rotate_conversation(self) -> None:
        """Starts a new conversation.

        Protocol v1 carries no conversation_id, so a turn arriving with no history starts
        a new thread. The chat header's "+" reset produces that (ChatService). See
        docs/protocol.md.
        """
        self.conversation_id = str(uuid.uuid4())


@router.websocket("/ws/v1")
async def agent_socket(websocket: WebSocket) -> None:
    settings = get_settings()

    if not origin_allowed(websocket.headers.get("origin"), settings.origin_allowlist):
        logger.info("rejected websocket from origin %s", websocket.headers.get("origin"))
        await websocket.close(code=CLOSE_POLICY)
        return

    offered = list(websocket.scope.get("subprotocols") or [])
    presented = websocket.headers.get("x-api-key") or key_from_subprotocols(offered)
    if not key_matches(settings.api_key, presented):
        logger.info("rejected websocket with missing or wrong key")
        await websocket.close(code=CLOSE_POLICY)
        return

    key = client_key(websocket.headers.get("x-forwarded-for"), _peer(websocket))
    registry = websocket.app.state.connections
    limiter = websocket.app.state.limiter

    try:
        with registry.hold(key):
            # Echo the offered subprotocol back: a browser that sent one expects the
            # handshake to name it.
            await websocket.accept(subprotocol=offered[0] if offered else None)
            await _serve(websocket, key=key, limiter=limiter)
    except TooManyConnections:
        logger.info("refused connection: %s already has too many", key)
        await websocket.close(code=CLOSE_POLICY)
    finally:
        if registry.is_idle(key):
            limiter.forget(key)


def _peer(websocket: WebSocket) -> str | None:
    client = websocket.client
    return client.host if client else None


async def _serve(websocket: WebSocket, *, key: str, limiter: Any) -> None:
    settings = get_settings()
    exchange = Exchange(websocket)
    base_url = resolve_base_url(websocket)

    try:
        while True:
            # receive_text() raises KeyError on a binary frame, which would escape as an
            # unhandled error and kill the connection.
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            raw = message.get("text")
            if not isinstance(raw, str):
                logger.info("dropping non-text frame from %s", key)
                continue

            if len(raw.encode("utf-8")) > settings.max_frame_bytes:
                logger.info("dropping oversized frame from %s", key)
                await _reject_unparsed(exchange, raw, i18n.too_long)
                continue

            event = parse_client_event(raw)
            if event is None:
                # A malformed `user_message` still has to terminate its exchange, or the
                # client waits forever for a turn that never started.
                await _reject_unparsed(exchange, raw, i18n.internal)
                continue

            if isinstance(event, Cancel):
                _cancel(exchange, event.id)
                continue

            if isinstance(event, UserMessage):
                await _accept_message(
                    event,
                    websocket=websocket,
                    exchange=exchange,
                    limiter=limiter,
                    key=key,
                    base_url=base_url,
                )
    except WebSocketDisconnect:
        pass
    finally:
        if exchange.task is not None and not exchange.task.done():
            exchange.task.cancel()
            # Let the turn's own handler run so its `done` is attempted before the
            # socket goes away.
            await asyncio.gather(exchange.task, return_exceptions=True)
        if websocket.client_state is WebSocketState.CONNECTED:
            await websocket.close(code=CLOSE_GOING_AWAY)


def _cancel(exchange: Exchange, message_id: str) -> None:
    if exchange.task is None or exchange.task.done():
        return
    if exchange.active_message_id != message_id:
        return
    exchange.task.cancel()


async def _accept_message(
    message: UserMessage,
    *,
    websocket: WebSocket,
    exchange: Exchange,
    limiter: Any,
    key: str,
    base_url: str,
) -> None:
    settings = get_settings()
    lang: ProtocolLang = message.language

    if exchange.task is not None and not exchange.task.done():
        # docs/protocol.md: exchanges are not interleaved on one connection. The
        # frontend disables the composer mid-turn, so this is a misbehaving client.
        await _terminate(exchange, message.id, code="bad_request", text=i18n.interleaved(lang))
        return

    if not websocket.app.state.gateway.is_production:
        # Refused here, not in the loop, so run_turn stays usable against the stand-in
        # (evals/run.py). Before the limiter: refusing is free, so it costs no allowance.
        logger.warning("refusing turn %s: MCP_SERVER_URL is not set", message.id)
        await _terminate(exchange, message.id, code="internal", text=i18n.mcp_not_configured(lang))
        # Recorded, unlike the client-fault rejections below: it is the only measure of
        # demand while the chat has no geodata server. Throttled, or an unauthenticated
        # caller could drive unbounded DynamoDB writes. Spending a token is free of
        # consequence here: is_production is fixed per process, so this branch and the
        # served path are mutually exclusive.
        if limiter.allow(key):
            await _record(websocket, message, exchange, TurnStats(error_code="mcp_not_configured"))
        return

    if len(message.content) > settings.max_message_chars:
        await _terminate(exchange, message.id, code="bad_request", text=i18n.too_long(lang))
        return

    if not limiter.allow(key):
        logger.info("rate limited %s", key)
        await _terminate(exchange, message.id, code="bad_request", text=i18n.too_many(lang))
        return

    if not message.history:
        exchange.rotate_conversation()

    exchange.active_message_id = message.id
    exchange.task = asyncio.create_task(
        _run(message, websocket=websocket, exchange=exchange, base_url=base_url)
    )


async def _reject_unparsed(
    exchange: Exchange, raw: str, message: Callable[[ProtocolLang], str]
) -> None:
    """Terminates an exchange for a frame that never became a ClientEvent.

    Only a recognisable `user_message` gets a reply: the protocol says unknown event types
    are ignored, and an event with no usable id cannot be answered at all.
    """
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return
    if not isinstance(data, dict) or data.get("type") != "user_message":
        return
    message_id = data.get("id")
    if not isinstance(message_id, str) or not message_id:
        return
    await _terminate(
        exchange, message_id, code="bad_request", text=message(coerce_lang(data.get("lang")))
    )


async def _terminate(exchange: Exchange, message_id: str, *, code: Any, text: str) -> None:
    """Ends an exchange that never started, keeping the one-error-then-done rule."""
    await exchange.send(Error(message_id=message_id, code=code, message=text))
    await exchange.send(Done(message_id=message_id))


async def _record(
    websocket: WebSocket, message: UserMessage, exchange: Exchange, stats: TurnStats
) -> None:
    """Logs a turn that ended before the agent loop ran. Never raises."""
    try:
        await _log_turn(websocket, message, exchange.conversation_id, stats, 0)
    except Exception:
        logger.warning("failed to log turn %s", message.id, exc_info=True)


async def _run(
    message: UserMessage,
    *,
    websocket: WebSocket,
    exchange: Exchange,
    base_url: str,
) -> None:
    settings = get_settings()
    lang: ProtocolLang = message.language
    stats = TurnStats()
    started = asyncio.get_running_loop().time()
    terminated = False

    try:
        # aclosing, not a bare `async for`: run_turn holds the MCP session open across its
        # yields, and an abandoned generator is finalized later in a different task, which
        # anyio refuses for the transport's cancel scope.
        turn = run_turn(
            message,
            models=websocket.app.state.models,
            gateway=websocket.app.state.gateway,
            settings=settings,
            stats=stats,
            base_url=base_url,
        )
        budget = settings.turn_timeout_for(message.model)
        async with asyncio.timeout(budget), contextlib.aclosing(turn):
            async for event in turn:
                await exchange.send(event)
                if event.type in ("final", "error"):
                    terminated = True
    except TimeoutError:
        stats.error_code = "timeout"
        logger.warning("turn %s timed out", message.id)
        if not terminated:
            await exchange.send(
                Error(message_id=message.id, code="timeout", message=i18n.timed_out(lang))
            )
            terminated = True
    except asyncio.CancelledError:
        stats.error_code = "cancelled"
        if not terminated:
            await exchange.send(
                Error(message_id=message.id, code="cancelled", message=i18n.cancelled(lang))
            )
            terminated = True
        # Not re-raised: cancellation is a normal protocol outcome and the `done` below
        # still has to be sent.
    except Exception:
        stats.error_code = "internal"
        logger.exception("turn %s failed", message.id)
        if not terminated:
            await exchange.send(
                Error(message_id=message.id, code="internal", message=i18n.internal(lang))
            )
            terminated = True
    finally:
        await exchange.send(Done(message_id=message.id))
        exchange.active_message_id = None
        elapsed_ms = int((asyncio.get_running_loop().time() - started) * 1000)
        # Last statement of the turn task: anything escaping here surfaces as an
        # unretrieved task exception long after the user had their answer.
        try:
            await _log_turn(websocket, message, exchange.conversation_id, stats, elapsed_ms)
        except Exception:
            logger.warning("failed to log turn %s", message.id, exc_info=True)


async def _log_turn(
    websocket: WebSocket,
    message: UserMessage,
    conversation_id: str,
    stats: TurnStats,
    elapsed_ms: int,
) -> None:
    logger.info(
        "turn %s lang=%s model=%s tools=%s layers=%d %dms%s",
        message.id,
        message.language,
        stats.model_id or "-",
        ",".join(stats.tool_calls) or "-",
        stats.layer_count,
        elapsed_ms,
        f" error={stats.error_code}" if stats.error_code else "",
    )
    await websocket.app.state.store.record_turn(
        conversation_id=conversation_id,
        message_id=message.id,
        lang=message.language,
        user_message=message.content,
        assistant_markdown=stats.markdown,
        model_id=stats.model_id,
        tool_calls=stats.tool_calls,
        layer_count=stats.layer_count,
        latency_ms=elapsed_ms,
        input_tokens=stats.input_tokens,
        output_tokens=stats.output_tokens,
        error_code=stats.error_code,
    )
