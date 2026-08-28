"""The /ws/v1 endpoint, driven over a real WebSocket by Starlette's TestClient.

These are the tests that hold the user-visible guarantees: every exchange terminates,
`done` always arrives last, a cancel is honoured, and a misbehaving client cannot make
the socket hang.
"""

from __future__ import annotations

import asyncio
import json
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.agent.models import NoModelAvailable
from app.config import Settings, get_settings
from app.limits import ConnectionRegistry, RateLimiter
from app.mcp.client import NO_TOOLS, ToolOutcome
from app.ws import router
from tests.conftest import (
    FakeGateway,
    FakeModels,
    FakeStore,
    FakeToolSession,
    text_result,
    tool_result,
)


def build_app(
    *,
    settings: Settings,
    models: Any,
    gateway: Any = None,
    store: Any = None,
) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.settings = settings
    app.state.models = models
    app.state.gateway = gateway or FakeGateway(NO_TOOLS)
    app.state.store = store or FakeStore()
    app.state.limiter = RateLimiter(settings.rate_limit_messages_per_minute)
    app.state.connections = ConnectionRegistry(limit=settings.max_connections_per_ip)
    return app


@pytest.fixture(autouse=True)
def _isolate_settings(settings: Settings, monkeypatch: pytest.MonkeyPatch) -> None:
    """get_settings is process-cached; each test needs its own configuration."""
    get_settings.cache_clear()
    monkeypatch.setattr("app.ws.get_settings", lambda: settings)


def _user_message(content: str = "Hallo", message_id: str = "m1", **extra: Any) -> str:
    payload: dict[str, Any] = {
        "type": "user_message",
        "id": message_id,
        "content": content,
        "lang": "de",
    }
    payload.update(extra)
    return json.dumps(payload)


def _first(frames: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    return next(frame for frame in frames if frame["type"] == kind)


def _drain(ws: Any, message_id: str = "m1") -> list[dict[str, Any]]:
    """Reads frames until `done`, which the protocol guarantees terminates an exchange."""
    frames: list[dict[str, Any]] = []
    while True:
        frame = json.loads(ws.receive_text())
        frames.append(frame)
        if frame["type"] == "done" and frame["message_id"] == message_id:
            return frames


def test_a_turn_ends_with_final_then_done(settings, server_event_validator) -> None:
    app = build_app(settings=settings, models=FakeModels([text_result("## Antwort")]))
    with TestClient(app).websocket_connect("/ws/v1") as ws:
        ws.send_text(_user_message())
        frames = _drain(ws)

    for frame in frames:
        server_event_validator.validate(frame)
    kinds = [f["type"] for f in frames]
    assert kinds[-1] == "done"
    assert kinds.count("final") == 1
    assert kinds.count("error") == 0
    assert kinds.count("done") == 1


def test_an_error_turn_still_ends_with_done(settings) -> None:
    app = build_app(settings=settings, models=FakeModels([NoModelAvailable("blocked")]))
    with TestClient(app).websocket_connect("/ws/v1") as ws:
        ws.send_text(_user_message())
        frames = _drain(ws)

    kinds = [f["type"] for f in frames]
    assert kinds.count("error") == 1
    assert kinds[-1] == "done"


def test_sequential_exchanges_share_one_connection(settings) -> None:
    """docs/protocol.md: the server must accept multiple sequential exchanges."""
    app = build_app(
        settings=settings, models=FakeModels([text_result("eins"), text_result("zwei")])
    )
    with TestClient(app).websocket_connect("/ws/v1") as ws:
        ws.send_text(_user_message(message_id="m1"))
        first = _drain(ws, "m1")
        ws.send_text(_user_message(message_id="m2", history=[{"role": "user", "content": "eins"}]))
        second = _drain(ws, "m2")

    assert _first(first, "final")["content_markdown"] == "eins"
    assert _first(second, "final")["content_markdown"] == "zwei"


def test_unknown_frames_are_ignored_not_fatal(settings) -> None:
    app = build_app(settings=settings, models=FakeModels([text_result("ok")]))
    with TestClient(app).websocket_connect("/ws/v1") as ws:
        ws.send_text("not json")
        ws.send_text(json.dumps({"type": "future_event", "id": "x"}))
        ws.send_text(_user_message())
        frames = _drain(ws)
    assert frames[-1]["type"] == "done"


def test_an_oversized_message_is_rejected_with_bad_request(settings) -> None:
    settings.max_message_chars = 20
    app = build_app(settings=settings, models=FakeModels([text_result("unused")]))
    with TestClient(app).websocket_connect("/ws/v1") as ws:
        ws.send_text(_user_message("x" * 500))
        frames = _drain(ws)

    error = _first(frames, "error")
    assert error["code"] == "bad_request"
    assert frames[-1]["type"] == "done"


def test_an_oversized_frame_is_dropped_without_killing_the_socket(settings) -> None:
    settings.max_frame_bytes = 200
    app = build_app(settings=settings, models=FakeModels([text_result("ok")]))
    with TestClient(app).websocket_connect("/ws/v1") as ws:
        ws.send_text(_user_message("y" * 5000))
        ws.send_text(_user_message())
        frames = _drain(ws)
    assert frames[-1]["type"] == "done"


def test_rate_limiting_terminates_the_exchange_cleanly(settings) -> None:
    settings.rate_limit_messages_per_minute = 1
    app = build_app(
        settings=settings, models=FakeModels([text_result("eins"), text_result("zwei")])
    )
    with TestClient(app).websocket_connect("/ws/v1") as ws:
        ws.send_text(_user_message(message_id="m1"))
        _drain(ws, "m1")
        ws.send_text(_user_message(message_id="m2", history=[{"role": "user", "content": "a"}]))
        frames = _drain(ws, "m2")

    error = _first(frames, "error")
    assert error["code"] == "bad_request"
    assert frames[-1]["type"] == "done"


def test_cancel_ends_the_turn_with_cancelled_then_done(settings) -> None:
    class SlowModels:
        async def converse_with_fallback(self, **kwargs: Any) -> Any:
            await asyncio.sleep(30)
            raise AssertionError("should have been cancelled")

    app = build_app(settings=settings, models=SlowModels())
    with TestClient(app).websocket_connect("/ws/v1") as ws:
        ws.send_text(_user_message())
        # The "thinking" step confirms the turn is in flight before cancelling.
        first = json.loads(ws.receive_text())
        assert first["type"] == "intermediate"
        ws.send_text(json.dumps({"type": "cancel", "id": "m1"}))
        frames = _drain(ws)

    error = _first(frames, "error")
    assert error["code"] == "cancelled"
    assert frames[-1]["type"] == "done"


def test_cancel_for_another_message_id_is_ignored(settings) -> None:
    app = build_app(settings=settings, models=FakeModels([text_result("fertig")]))
    with TestClient(app).websocket_connect("/ws/v1") as ws:
        ws.send_text(_user_message(message_id="m1"))
        ws.send_text(json.dumps({"type": "cancel", "id": "someone-else"}))
        frames = _drain(ws, "m1")
    assert any(f["type"] == "final" for f in frames)


def test_a_turn_that_overruns_its_budget_times_out(settings) -> None:
    settings.turn_timeout_seconds = 0.2

    class SlowModels:
        async def converse_with_fallback(self, **kwargs: Any) -> Any:
            await asyncio.sleep(10)
            raise AssertionError("unreachable")

    app = build_app(settings=settings, models=SlowModels())
    with TestClient(app).websocket_connect("/ws/v1") as ws:
        ws.send_text(_user_message())
        frames = _drain(ws)

    error = _first(frames, "error")
    assert error["code"] == "timeout"
    assert frames[-1]["type"] == "done"


def test_a_rejected_origin_never_gets_a_socket(settings) -> None:
    settings.allowed_origins = "https://denpw8uo5zpkl.cloudfront.net"
    app = build_app(settings=settings, models=FakeModels([text_result("x")]))
    client = TestClient(app)
    with (
        pytest.raises(WebSocketDisconnect),
        client.websocket_connect("/ws/v1", headers={"origin": "https://evil.test"}),
    ):
        pass


def test_the_configured_origin_is_accepted(settings) -> None:
    settings.allowed_origins = "https://denpw8uo5zpkl.cloudfront.net"
    app = build_app(settings=settings, models=FakeModels([text_result("ok")]))
    with TestClient(app).websocket_connect(
        "/ws/v1", headers={"origin": "https://denpw8uo5zpkl.cloudfront.net"}
    ) as ws:
        ws.send_text(_user_message())
        assert _drain(ws)[-1]["type"] == "done"


def test_the_api_key_is_enforced_only_when_configured(settings) -> None:
    settings.api_key = "s3cret"
    app = build_app(settings=settings, models=FakeModels([text_result("ok")]))
    client = TestClient(app)

    with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/v1"):
        pass

    # Browsers cannot set headers on a WebSocket, so the key rides the subprotocol.
    with client.websocket_connect("/ws/v1", subprotocols=["sgs-llm-key.s3cret"]) as ws:
        ws.send_text(_user_message())
        assert _drain(ws)[-1]["type"] == "done"


def test_the_conversation_id_rotates_only_on_a_fresh_thread(settings) -> None:
    store = FakeStore()
    app = build_app(
        settings=settings,
        models=FakeModels([text_result("a"), text_result("b"), text_result("c")]),
        store=store,
    )
    with TestClient(app).websocket_connect("/ws/v1") as ws:
        ws.send_text(_user_message(message_id="m1"))
        _drain(ws, "m1")
        # A follow-up carries history, so it belongs to the same conversation.
        ws.send_text(_user_message(message_id="m2", history=[{"role": "user", "content": "a"}]))
        _drain(ws, "m2")
        # The chat header's "+" reset sends no history: a new conversation.
        ws.send_text(_user_message(message_id="m3"))
        _drain(ws, "m3")

    ids = [turn["conversation_id"] for turn in store.turns]
    assert len(ids) == 3
    assert ids[0] == ids[1]
    assert ids[2] != ids[0]


def test_every_turn_is_logged_including_failures(settings) -> None:
    store = FakeStore()
    app = build_app(
        settings=settings, models=FakeModels([NoModelAvailable("blocked")]), store=store
    )
    with TestClient(app).websocket_connect("/ws/v1") as ws:
        ws.send_text(_user_message("Wie viele Kantone?"))
        _drain(ws)

    assert len(store.turns) == 1
    turn = store.turns[0]
    assert turn["user_message"] == "Wie viele Kantone?"
    assert turn["error_code"] == "internal"
    assert turn["lang"] == "de"


def test_a_storage_failure_does_not_break_the_answer(settings) -> None:
    class BrokenStore(FakeStore):
        async def record_turn(self, **kwargs: Any) -> None:
            raise RuntimeError("dynamodb is down")

    app = build_app(
        settings=settings, models=FakeModels([text_result("Antwort")]), store=BrokenStore()
    )
    with TestClient(app).websocket_connect("/ws/v1") as ws:
        ws.send_text(_user_message())
        frames = _drain(ws)

    assert any(f["type"] == "final" for f in frames)


def test_a_turn_is_refused_when_no_production_mcp_is_configured(settings) -> None:
    """Out of the box: the service is up with nothing to answer from, and must still
    terminate the exchange rather than fall back to the stand-in."""
    models = FakeModels([text_result("should never be reached")])
    app = build_app(
        settings=settings,
        models=models,
        gateway=FakeGateway(NO_TOOLS, is_production=False),
    )
    with TestClient(app).websocket_connect("/ws/v1") as ws:
        ws.send_text(_user_message("Zeige mir die Hochwasser-Messstationen im Wallis"))
        frames = _drain(ws)

    assert [f["type"] for f in frames] == ["error", "done"]
    assert _first(frames, "error")["code"] == "internal"
    # The model is never consulted, so a refused turn spends no Bedrock tokens.
    assert models.calls == []


def test_the_refusal_is_localized_and_mentions_the_map_still_works(settings) -> None:
    app = build_app(
        settings=settings,
        models=FakeModels([]),
        gateway=FakeGateway(NO_TOOLS, is_production=False),
    )
    with TestClient(app).websocket_connect("/ws/v1") as ws:
        ws.send_text(_user_message("Bonjour", **{"lang": "fr"}))
        frames = _drain(ws)

    message = _first(frames, "error")["message"]
    assert "géodonnées" in message
    assert "carte" in message


def test_the_refusal_does_not_consume_the_rate_limit(settings) -> None:
    """Refusing is free, so it must not spend the client's allowance."""
    app = build_app(
        settings=settings,
        models=FakeModels([]),
        gateway=FakeGateway(NO_TOOLS, is_production=False),
    )
    with TestClient(app).websocket_connect("/ws/v1") as ws:
        for index in range(settings.rate_limit_messages_per_minute + 3):
            message_id = f"m{index}"
            ws.send_text(_user_message("Hallo", message_id=message_id))
            frames = _drain(ws, message_id)
            assert _first(frames, "error")["code"] == "internal"


def test_a_configured_but_toolless_mcp_still_answers(settings) -> None:
    """Only *unconfigured* refuses: a configured-but-toolless server must still degrade
    the documented way rather than refuse."""
    app = build_app(
        settings=settings,
        models=FakeModels([text_result("Ich konnte die Fachdaten nicht abfragen.")]),
        gateway=FakeGateway(NO_TOOLS, is_production=True),
    )
    with TestClient(app).websocket_connect("/ws/v1") as ws:
        ws.send_text(_user_message("Hallo"))
        frames = _drain(ws)

    assert _first(frames, "final")["content_markdown"].startswith("Ich konnte")


def test_a_refused_turn_is_recorded(settings) -> None:
    """While the chat has no geodata server, this count is the only demand signal."""
    store = FakeStore()
    app = build_app(
        settings=settings,
        models=FakeModels([]),
        gateway=FakeGateway(NO_TOOLS, is_production=False),
        store=store,
    )
    with TestClient(app).websocket_connect("/ws/v1") as ws:
        ws.send_text(_user_message("Hallo"))
        _drain(ws)

    assert len(store.turns) == 1
    assert store.turns[0]["error_code"] == "mcp_not_configured"
    assert store.turns[0]["user_message"] == "Hallo"


def test_a_storage_failure_does_not_break_the_refusal(settings) -> None:
    class BrokenStore(FakeStore):
        async def record_turn(self, **kwargs: Any) -> None:
            raise RuntimeError("dynamodb is down")

    app = build_app(
        settings=settings,
        models=FakeModels([]),
        gateway=FakeGateway(NO_TOOLS, is_production=False),
        store=BrokenStore(),
    )
    with TestClient(app).websocket_connect("/ws/v1") as ws:
        ws.send_text(_user_message())
        frames = _drain(ws)

    assert [f["type"] for f in frames] == ["error", "done"]


def test_refusal_recording_is_throttled(settings) -> None:
    """The refusal itself is always answered, but an unauthenticated caller must not be
    able to drive unbounded DynamoDB writes with it."""
    settings.rate_limit_messages_per_minute = 2
    store = FakeStore()
    app = build_app(
        settings=settings,
        models=FakeModels([]),
        gateway=FakeGateway(NO_TOOLS, is_production=False),
        store=store,
    )
    with TestClient(app).websocket_connect("/ws/v1") as ws:
        for index in range(6):
            message_id = f"m{index}"
            ws.send_text(_user_message("Hallo", message_id=message_id))
            frames = _drain(ws, message_id)
            # Every message still gets the informative refusal, not a rate-limit error.
            assert _first(frames, "error")["code"] == "internal"

    assert len(store.turns) == 2, "writes stop at the limit; refusals do not"


def test_reconnecting_does_not_reset_the_rate_limit(settings) -> None:
    """The limiter is dropped when a client's last connection closes, so a client that
    reconnects between messages must not get a fresh allowance."""
    settings.rate_limit_messages_per_minute = 2
    store = FakeStore()
    app = build_app(
        settings=settings,
        models=FakeModels([]),
        gateway=FakeGateway(NO_TOOLS, is_production=False),
        store=store,
    )
    client = TestClient(app)
    for connection in range(6):
        with client.websocket_connect("/ws/v1") as ws:
            for index in range(3):
                message_id = f"c{connection}m{index}"
                ws.send_text(_user_message("Hallo", message_id=message_id))
                _drain(ws, message_id)

    assert len(store.turns) == 2, "the allowance must survive a reconnect"


def test_a_binary_frame_is_dropped_without_killing_the_socket(settings) -> None:
    """receive_text() raises KeyError on a binary frame; that escaped as an unhandled
    error and closed the connection."""
    app = build_app(settings=settings, models=FakeModels([text_result("ok")]))
    with TestClient(app).websocket_connect("/ws/v1") as ws:
        ws.send_bytes(b"\x00\x01\x02")
        ws.send_text(_user_message())
        frames = _drain(ws)
    assert any(f["type"] == "final" for f in frames)


def test_an_oversized_user_message_still_terminates_its_exchange(settings) -> None:
    settings.max_frame_bytes = 200
    app = build_app(settings=settings, models=FakeModels([text_result("unused")]))
    with TestClient(app).websocket_connect("/ws/v1") as ws:
        ws.send_text(_user_message("y" * 5000))
        frames = _drain(ws)
    assert [f["type"] for f in frames] == ["error", "done"]
    assert _first(frames, "error")["code"] == "bad_request"


def test_a_malformed_user_message_still_terminates_its_exchange(settings) -> None:
    """A known event type with bad fields cannot be dropped silently: the frontend has a
    pending assistant message that would never resolve."""
    app = build_app(settings=settings, models=FakeModels([text_result("unused")]))
    with TestClient(app).websocket_connect("/ws/v1") as ws:
        ws.send_text(
            json.dumps(
                {
                    "type": "user_message",
                    "id": "m1",
                    "content": "x",
                    "map_context": {"bbox": [1, 2, 3]},
                }
            )
        )
        frames = _drain(ws)
    assert [f["type"] for f in frames] == ["error", "done"]


def test_an_unknown_event_type_is_still_dropped_silently(settings) -> None:
    """The protocol requires forward compatibility, so a future event type must not draw
    an error."""
    app = build_app(settings=settings, models=FakeModels([text_result("ok")]))
    with TestClient(app).websocket_connect("/ws/v1") as ws:
        ws.send_text(json.dumps({"type": "future_event", "id": "x"}))
        ws.send_text(_user_message())
        frames = _drain(ws)
    assert [f["message_id"] for f in frames] == ["m1"] * len(frames)


def test_the_interleave_rejection_says_a_request_is_running(settings) -> None:
    class SlowModels:
        async def converse_with_fallback(self, **kwargs: Any) -> Any:
            await asyncio.sleep(30)
            raise AssertionError("unreachable")

    app = build_app(settings=settings, models=SlowModels())
    with TestClient(app).websocket_connect("/ws/v1") as ws:
        ws.send_text(_user_message(message_id="m1"))
        assert json.loads(ws.receive_text())["type"] == "intermediate"
        ws.send_text(_user_message(message_id="m2"))
        frames = _drain(ws, "m2")
    error = _first(frames, "error")
    assert error["code"] == "bad_request"
    assert "läuft" in error["message"]


async def test_a_timed_out_turn_closes_its_tool_session_in_its_own_task(settings) -> None:
    """run_turn holds the MCP session open across its yields. Abandoning the generator
    leaves the event loop to finalize it in a different task, which anyio refuses for the
    transport's cancel scope, leaking the session and raising out of band."""
    settings.turn_timeout_seconds = 0.05
    teardowns: list[tuple[str, str]] = []

    class SlowTools(FakeToolSession):
        async def call(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
            await asyncio.sleep(1)
            raise AssertionError("should have timed out")

    class TrackingGateway:
        is_production = True

        @asynccontextmanager
        async def session(self) -> Any:
            current = asyncio.current_task()
            entered = current.get_name() if current else "?"
            try:
                yield SlowTools({"t": ToolOutcome(text="{}", data={}, is_error=False)}, specs=["t"])
            finally:
                now = asyncio.current_task()
                teardowns.append((entered, now.get_name() if now else "?"))

    models = FakeModels([tool_result("t", {}, "tu1"), text_result("unused")])
    app = build_app(settings=settings, models=models, gateway=TrackingGateway())
    with TestClient(app).websocket_connect("/ws/v1") as ws:
        ws.send_text(_user_message())
        frames = _drain(ws)

    assert _first(frames, "error")["code"] == "timeout"
    assert teardowns, "the session must have been opened and closed"
    entered, exited = teardowns[-1]
    assert entered == exited, f"session torn down in {exited}, opened in {entered}"


def test_apertus_gets_its_own_turn_budget(settings) -> None:
    """~16.8 tok/s across up to 8 tool iterations does not fit the Bedrock models' 90 s,
    and raising it for everyone would loosen the Bedrock path too."""
    settings.turn_timeout_seconds = 0.05
    settings.apertus_turn_timeout_seconds = 30.0
    settings.apertus_base_url = "http://10.0.0.1:8000/v1"

    class SlowModels:
        async def converse_with_fallback(self, **kwargs: Any) -> Any:
            await asyncio.sleep(0.3)
            return text_result("langsam, aber fertig")

    app = build_app(settings=settings, models=SlowModels())
    with TestClient(app).websocket_connect("/ws/v1") as ws:
        ws.send_text(_user_message(model="apertus"))
        frames = _drain(ws)

    assert not any(frame["type"] == "error" for frame in frames)
    assert _first(frames, "final")["content_markdown"] == "langsam, aber fertig"


def test_the_bedrock_budget_is_unchanged_by_the_apertus_one(settings) -> None:
    settings.turn_timeout_seconds = 0.05
    settings.apertus_turn_timeout_seconds = 30.0

    class SlowModels:
        async def converse_with_fallback(self, **kwargs: Any) -> Any:
            await asyncio.sleep(0.3)
            raise AssertionError("unreachable")

    app = build_app(settings=settings, models=SlowModels())
    with TestClient(app).websocket_connect("/ws/v1") as ws:
        ws.send_text(_user_message())
        frames = _drain(ws)

    assert _first(frames, "error")["code"] == "timeout"
