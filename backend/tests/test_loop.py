"""The agent loop's contract with the protocol.

The invariant under test throughout: zero or more `intermediate` events, then exactly
one `final` or `error` - never both, never neither.
"""

from __future__ import annotations

import asyncio
import json
from itertools import pairwise

from app.agent.bedrock import NoModelAvailable
from app.agent.loop import TurnStats, build_messages, run_turn
from app.mcp.client import NO_TOOLS, ToolOutcome
from app.protocol import HistoryEntry, UserMessage
from tests.conftest import (
    FakeGateway,
    FakeModels,
    FakeToolSession,
    text_result,
    tool_result,
)


def _message(content: str = "Hochwasser im Wallis", **kwargs: object) -> UserMessage:
    payload = {"type": "user_message", "id": "m1", "content": content, "lang": "de"}
    payload.update(kwargs)
    return UserMessage.model_validate(payload)


async def _collect(message, models, gateway, settings, stats):
    return [
        event
        async for event in run_turn(
            message, models=models, gateway=gateway, settings=settings, stats=stats
        )
    ]


async def test_plain_answer_emits_one_final(settings) -> None:
    from tests.conftest import FakeModels

    stats = TurnStats()
    events = await _collect(
        _message(), FakeModels([text_result("## Antwort")]), FakeGateway(NO_TOOLS), settings, stats
    )

    kinds = [e.type for e in events]
    assert kinds.count("final") == 1
    assert kinds.count("error") == 0
    assert kinds[-1] == "final"
    assert stats.markdown == "## Antwort"
    assert stats.input_tokens == 10


async def test_tool_call_streams_progress_and_attaches_the_layer(settings) -> None:
    from tests.conftest import FakeModels

    layer_payload = {
        "layer": {
            "id": "fs_1",
            "name": "Hochwasser-Gefahrenzonen",
            "format": "geojson",
            "url": "/data/fs_1.geojson",
            "geometry_type": "polygon",
            "feature_count": 5,
            "bbox": [7.0, 46.0, 8.0, 46.5],
        }
    }
    tools = FakeToolSession(
        {
            "display_layer": ToolOutcome(
                text=json.dumps(layer_payload), data=layer_payload, is_error=False
            )
        }
    )
    models = FakeModels(
        [
            tool_result("display_layer", {"result_id": "fs_1", "name": "Hochwasser"}),
            text_result("Die Zonen sind auf der Karte."),
        ]
    )

    stats = TurnStats()
    events = [
        event
        async for event in run_turn(
            _message(),
            models=models,
            gateway=FakeGateway(tools),
            settings=settings,
            stats=stats,
            base_url="https://example.test",
        )
    ]

    steps = [e for e in events if e.type == "intermediate"]
    assert any(s.status == "started" for s in steps)
    assert any(s.status == "finished" for s in steps)

    final = events[-1]
    assert final.type == "final"
    assert final.layers is not None and len(final.layers) == 1
    # A relative artifact path must be resolved against the public origin, or the
    # browser would fetch it from its own host.
    assert final.layers[0].url == "https://example.test/data/fs_1.geojson"
    assert stats.tool_calls == ["display_layer"]
    assert stats.layer_count == 1


async def test_slow_tool_repeats_started_keepalive_on_the_same_step(settings, monkeypatch) -> None:
    import app.agent.loop as loop_module

    monkeypatch.setattr(loop_module, "TOOL_KEEPALIVE_SECONDS", 0.01)

    class SlowTools(FakeToolSession):
        async def call(self, name, arguments):
            await asyncio.sleep(0.035)
            return await super().call(name, arguments)

    tools = SlowTools(
        {"search_layers": ToolOutcome(text="{}", data={}, is_error=False)},
        specs=["search_layers"],
    )
    models = FakeModels([tool_result("search_layers", {"query": "roads"}), text_result("Done")])

    events = await _collect(_message(), models, FakeGateway(tools), settings, TurnStats())

    tool_steps = [
        event for event in events if event.type == "intermediate" and event.step_id == "t1"
    ]
    assert len([event for event in tool_steps if event.status == "started"]) >= 2
    assert len([event for event in tool_steps if event.status == "finished"]) == 1


async def test_failed_tool_is_reported_and_the_turn_still_answers(settings) -> None:
    from tests.conftest import FakeModels

    tools = FakeToolSession(
        {"search_layers": ToolOutcome(text="upstream 503", data=None, is_error=True)}
    )
    models = FakeModels(
        [
            tool_result("search_layers", {"query": "Hochwasser"}),
            text_result("Ich konnte die Datensätze nicht abfragen."),
        ]
    )

    events = await _collect(_message(), models, FakeGateway(tools), settings, TurnStats())
    assert any(e.type == "intermediate" and e.status == "failed" for e in events)
    assert events[-1].type == "final"


async def test_no_model_available_produces_one_error(settings) -> None:
    from tests.conftest import FakeModels

    stats = TurnStats()
    events = await _collect(
        _message(),
        FakeModels([NoModelAvailable("blocked")]),
        FakeGateway(NO_TOOLS),
        settings,
        stats,
    )
    assert [e.type for e in events].count("error") == 1
    assert events[-1].type == "error"
    assert events[-1].code == "internal"
    assert stats.error_code == "internal"


async def test_empty_model_output_is_an_error_not_an_empty_answer(settings) -> None:
    from tests.conftest import FakeModels

    events = await _collect(
        _message(), FakeModels([text_result("")]), FakeGateway(NO_TOOLS), settings, TurnStats()
    )
    assert events[-1].type == "error"


async def test_last_iteration_steers_to_an_answer_without_withdrawing_the_tools(
    settings,
) -> None:
    """A model that keeps calling tools must be stopped - but not by removing the tools.

    Once the conversation holds toolUse/toolResult blocks, Bedrock rejects the request
    with ValidationException if no toolConfig accompanies them. Withdrawing the tool set
    therefore broke exactly the multi-step turns the loop exists for, so the loop steers
    with an instruction instead and keeps toolConfig attached throughout.
    """
    from tests.conftest import FakeModels

    tools = FakeToolSession({"search_layers": ToolOutcome(text="{}", data={}, is_error=False)})
    models = FakeModels([tool_result("search_layers", {"query": "x"}) for _ in range(10)])

    events = await _collect(_message(), models, FakeGateway(tools), settings, TurnStats())

    assert models.calls[-1]["tools"] is not None, "toolConfig must stay attached"
    last_messages = json.dumps(models.calls[-1]["messages"])
    assert "Do not call any more tools" in last_messages
    assert events[-1].type in ("final", "error")
    assert len([e for e in events if e.type in ("final", "error")]) == 1


async def test_the_nudge_never_breaks_bedrocks_role_alternation(settings) -> None:
    """The nudge lands after a toolResult message, which is itself user-role."""
    from tests.conftest import FakeModels

    tools = FakeToolSession({"search_layers": ToolOutcome(text="{}", data={}, is_error=False)})
    models = FakeModels([tool_result("search_layers", {"query": "x"}) for _ in range(10)])

    await _collect(_message(), models, FakeGateway(tools), settings, TurnStats())
    for call in models.calls:
        roles = [m["role"] for m in call["messages"]]
        assert all(a != b for a, b in pairwise(roles)), roles


async def test_unusable_tool_calls_are_retried_not_echoed_back(settings) -> None:
    """Observed from Mistral: toolUse blocks with no name and no id.

    Echoing one back sends an empty toolUseId, which botocore rejects client-side and
    kills the turn. The assistant turn must be dropped and the model asked again.
    """
    from tests.conftest import FakeModels, malformed_tool_result

    models = FakeModels([malformed_tool_result(), text_result("Antwort nach dem Retry.")])
    tools = FakeToolSession({"search_layers": ToolOutcome(text="{}", data={}, is_error=False)})

    events = await _collect(_message(), models, FakeGateway(tools), settings, TurnStats())

    assert events[-1].type == "final"
    assert events[-1].content_markdown == "Antwort nach dem Retry."
    # The unusable assistant turn must not appear in the follow-up request.
    assert "toolUse" not in json.dumps(models.calls[-1]["messages"])


async def test_tools_unavailable_adds_the_no_tools_note(settings) -> None:
    from tests.conftest import FakeModels

    models = FakeModels([text_result("Antwort ohne Werkzeuge")])
    await _collect(_message(), models, FakeGateway(NO_TOOLS), settings, TurnStats())
    assert "tools are unavailable" in models.calls[0]["system"]


async def test_map_context_reaches_the_prompt(settings) -> None:
    from tests.conftest import FakeModels

    models = FakeModels([text_result("ok")])
    message = _message(
        "Was ist hier?", map_context={"bbox": [7.1, 46.2, 7.3, 46.4], "active_layer_ids": ["ch.x"]}
    )
    await _collect(message, models, FakeGateway(NO_TOOLS), settings, TurnStats())
    system = models.calls[0]["system"]
    assert "7.1000" in system
    assert "ch.x" in system


class TestBuildMessages:
    def test_appends_the_current_message(self) -> None:
        messages = build_messages([], "Hallo", limit=10)
        assert messages == [{"role": "user", "content": [{"text": "Hallo"}]}]

    def test_drops_a_leading_assistant_turn(self) -> None:
        """A truncated history window can start mid-exchange; Bedrock requires a user
        turn first."""
        history = [
            HistoryEntry(role="assistant", content="earlier answer"),
            HistoryEntry(role="user", content="earlier question"),
        ]
        messages = build_messages(history, "now", limit=10)
        assert messages[0]["role"] == "user"
        assert "earlier answer" not in json.dumps(messages)

    def test_merges_consecutive_same_role_turns(self) -> None:
        history = [
            HistoryEntry(role="user", content="a"),
            HistoryEntry(role="user", content="b"),
        ]
        messages = build_messages(history, "c", limit=10)
        assert len(messages) == 1
        assert messages[0]["content"][0]["text"] == "a\n\nb\n\nc"

    def test_alternates_roles(self) -> None:
        history = [
            HistoryEntry(role="user", content="q1"),
            HistoryEntry(role="assistant", content="a1"),
            HistoryEntry(role="user", content="q2"),
            HistoryEntry(role="assistant", content="a2"),
        ]
        messages = build_messages(history, "q3", limit=10)
        assert [m["role"] for m in messages] == ["user", "assistant", "user", "assistant", "user"]

    def test_honours_the_history_limit(self) -> None:
        history = [HistoryEntry(role="user", content=f"q{i}") for i in range(50)]
        messages = build_messages(history, "now", limit=4)
        assert "q0" not in json.dumps(messages)

    def test_empty_content_never_produces_an_empty_message(self) -> None:
        """Bedrock rejects empty text blocks."""
        messages = build_messages([HistoryEntry(role="user", content="   ")], "", limit=10)
        assert messages[-1]["content"][0]["text"].strip() != ""


async def test_exhausting_the_tool_budget_keeps_a_usable_answer(settings) -> None:
    """A model that never stops calling tools still produced text and layers; discarding
    them for `error internal` loses a usable answer and an already-published map layer."""
    layer = {
        "layer": {
            "id": "L1",
            "name": "Messstationen",
            "format": "geojson",
            "url": "https://x/a.geojson",
            "geometry_type": "point",
        }
    }
    session = FakeToolSession(
        {"t": ToolOutcome(text=json.dumps(layer), data=layer, is_error=False)}
    )
    script = []
    for index in range(10):
        result = tool_result("t", {}, f"tu{index}")
        result.text = "1 Messstation gefunden."
        script.append(result)

    events = await _collect(
        _message("Zeige Messstationen"),
        FakeModels(script),
        FakeGateway(session),
        settings,
        TurnStats(),
    )
    final = events[-1]
    assert final.type == "final"
    assert final.content_markdown == "1 Messstation gefunden."
    assert final.layers is not None and len(final.layers) == 1


async def test_catalog_layers_are_withheld_until_the_client_supports_them(settings) -> None:
    """The field is a proposed protocol addition the frontend drops, so emitting it would
    have the agent claim a layer is on the map when nothing was added."""
    payload = {
        "catalog_layer": {"id": "ch.bafu.aquaprotect_100"},
        "focus_bbox": [7.3, 46.9, 7.5, 47.0],
    }
    session = FakeToolSession(
        {
            "display_catalog_layer": ToolOutcome(
                text=json.dumps(payload), data=payload, is_error=False
            )
        }
    )
    models = FakeModels(
        [
            tool_result("display_catalog_layer", {"layer_id": "ch.bafu.aquaprotect_100"}),
            text_result("Der Datensatz heisst Aquaprotect."),
        ]
    )

    assert settings.enable_catalog_layers is False
    events = await _collect(_message(), models, FakeGateway(session), settings, TurnStats())
    final = events[-1]
    assert final.type == "final"
    assert final.catalog_layers is None
    assert final.focus_bbox is None
    # And the model is told not to promise it.
    assert "cannot put raster or image layers" in models.calls[0]["system"]
