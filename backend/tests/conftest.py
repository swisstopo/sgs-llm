"""Shared fixtures.

Nothing here touches AWS or the network. The model and tool layers are replaced by fakes,
so the whole agent loop runs offline.
"""

from __future__ import annotations

import json
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest

from app.agent.bedrock import (
    ConverseResult,
    ModelHandle,
    NoModelAvailable,
    SystemPrompt,
    ToolUse,
    resolve_system,
)
from app.config import Settings
from app.mcp.client import ToolOutcome, ToolSession

REPO_ROOT = Path(__file__).resolve().parents[2]
SERVER_EVENTS_SCHEMA = REPO_ROOT / "docs" / "protocol" / "server-events.schema.json"


@pytest.fixture(scope="session")
def server_event_validator() -> Any:
    """Validates frames against the published schema, not against a copy of it."""
    from jsonschema import Draft202012Validator

    schema = json.loads(SERVER_EVENTS_SCHEMA.read_text(encoding="utf-8"))
    return Draft202012Validator(schema)


@pytest.fixture
def settings() -> Settings:
    return Settings(
        bedrock_primary_model_id="test.primary",
        bedrock_secondary_model_id="test.secondary",
        bedrock_region="eu-central-1",
        bedrock_secondary_region="eu-west-1",
        turn_timeout_seconds=5.0,
        max_tool_iterations=4,
    )


HANDLE = ModelHandle(model_id="test.primary", region="eu-central-1", role="primary")


class FakeModels:
    """Replays a scripted sequence of Converse results."""

    def __init__(self, script: list[ConverseResult | Exception]) -> None:
        self._script = list(script)
        self.calls: list[dict[str, Any]] = []

    async def converse_with_fallback(
        self,
        *,
        messages: list[dict[str, Any]],
        system: SystemPrompt,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 2048,
        pinned: ModelHandle | None = None,
    ) -> ConverseResult:
        # Rendered here, as the real client does per attempt, so `calls[...]["system"]`
        # is the prompt the model would actually have seen.
        handle = pinned or HANDLE
        self.calls.append(
            {
                "messages": list(messages),
                "system": resolve_system(system, handle),
                "tools": tools,
                "handle": handle,
            }
        )
        if not self._script:
            raise NoModelAvailable("script exhausted")
        nxt = self._script.pop(0)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt


def text_result(text: str) -> ConverseResult:
    return ConverseResult(
        handle=HANDLE,
        stop_reason="end_turn",
        text=text,
        assistant_message={"role": "assistant", "content": [{"text": text}]},
        input_tokens=10,
        output_tokens=5,
    )


def tool_result(name: str, arguments: dict[str, Any], tool_use_id: str = "tu1") -> ConverseResult:
    return ConverseResult(
        handle=HANDLE,
        stop_reason="tool_use",
        text="",
        tool_uses=[ToolUse(tool_use_id=tool_use_id, name=name, arguments=arguments)],
        assistant_message={
            "role": "assistant",
            "content": [{"toolUse": {"toolUseId": tool_use_id, "name": name, "input": arguments}}],
        },
        input_tokens=8,
        output_tokens=4,
    )


def malformed_tool_result() -> ConverseResult:
    """A response whose only toolUse block has no name and no id - the shape Mistral
    actually returned on Bedrock, which botocore then refuses to echo back."""
    return ConverseResult(
        handle=HANDLE,
        stop_reason="tool_use",
        text="",
        tool_uses=[],
        assistant_message={"role": "assistant", "content": [{"toolUse": {"input": {}}}]},
        malformed_tool_uses=1,
        input_tokens=6,
        output_tokens=2,
    )


class FakeToolSession(ToolSession):
    def __init__(self, outcomes: dict[str, ToolOutcome], specs: list[str] | None = None) -> None:
        super().__init__(None, [_spec(name) for name in (specs or list(outcomes))])
        self._outcomes = outcomes
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def call(self, name: str, arguments: dict[str, Any]) -> ToolOutcome:
        self.calls.append((name, arguments))
        return self._outcomes.get(
            name, ToolOutcome(text=f"no such tool {name}", data=None, is_error=True)
        )


def _spec(name: str) -> dict[str, Any]:
    return {
        "toolSpec": {
            "name": name,
            "description": name,
            "inputSchema": {"json": {"type": "object", "properties": {}}},
        }
    }


class FakeGateway:
    # Production by default so the ws tests exercise the served path.
    def __init__(self, session: ToolSession, *, is_production: bool = True) -> None:
        self._session = session
        self.is_production = is_production

    @asynccontextmanager
    async def session(self) -> Any:
        yield self._session


class FakeStore:
    def __init__(self) -> None:
        self.feedback: list[dict[str, Any]] = []
        self.turns: list[dict[str, Any]] = []

    async def record_feedback(self, **kwargs: Any) -> str:
        self.feedback.append(kwargs)
        return "fake-id"

    async def record_turn(self, **kwargs: Any) -> None:
        self.turns.append(kwargs)
