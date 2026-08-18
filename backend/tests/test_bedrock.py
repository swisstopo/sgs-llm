"""The model layer: response parsing, and the fallback behaviour the pilot depends on."""

from __future__ import annotations

from typing import Any

import pytest

from app.agent.bedrock import (
    BedrockModels,
    ModelHandle,
    NoModelAvailable,
    _parse_response,
    resolve_system,
    tool_result_block,
    tool_results_message,
)
from app.config import Settings
from tests.conftest import HANDLE


def _client_error(code: str) -> Exception:
    """A botocore-shaped error, since that is what the code classifies on."""

    class ClientError(Exception):
        def __init__(self) -> None:
            super().__init__(code)
            self.response = {"Error": {"Code": code, "Message": code}}

    return ClientError()


class FakeBedrockClient:
    def __init__(self, behaviour: Any) -> None:
        self._behaviour = behaviour
        self.calls: list[dict[str, Any]] = []

    def converse(self, **request: Any) -> dict[str, Any]:
        self.calls.append(request)
        if isinstance(self._behaviour, Exception):
            raise self._behaviour
        return self._behaviour


def _models(settings: Settings, clients: dict[str, FakeBedrockClient]) -> BedrockModels:
    models = BedrockModels(settings)
    models._clients.update(clients)
    return models


def _text_response(text: str) -> dict[str, Any]:
    return {
        "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
        "stopReason": "end_turn",
        "usage": {"inputTokens": 12, "outputTokens": 7},
    }


class TestParseResponse:
    def test_extracts_text_and_usage(self) -> None:
        result = _parse_response(HANDLE, _text_response("Drei Kantone: …"))
        assert result.text == "Drei Kantone: …"
        assert result.tool_uses == []
        assert (result.input_tokens, result.output_tokens) == (12, 7)

    def test_extracts_tool_use(self) -> None:
        response = {
            "output": {
                "message": {
                    "role": "assistant",
                    "content": [
                        {"text": "Ich suche."},
                        {
                            "toolUse": {
                                "toolUseId": "tu-1",
                                "name": "search_layers",
                                "input": {"query": "Hochwasser"},
                            }
                        },
                    ],
                }
            },
            "stopReason": "tool_use",
        }
        result = _parse_response(HANDLE, response)
        assert result.stop_reason == "tool_use"
        assert len(result.tool_uses) == 1
        assert result.tool_uses[0].name == "search_layers"
        assert result.tool_uses[0].arguments == {"query": "Hochwasser"}
        # The assistant message must be echoed back verbatim or Bedrock rejects the
        # follow-up.
        assert result.assistant_message["content"] == response["output"]["message"]["content"]

    def test_survives_a_response_with_no_content(self) -> None:
        result = _parse_response(HANDLE, {})
        assert result.text == ""
        assert result.tool_uses == []

    def test_a_mixed_response_drops_only_the_unusable_block(self) -> None:
        """Mistral can return one good toolUse alongside one with no name or id.

        Bedrock wants exactly one toolResult per block present in the echoed turn, so the
        unusable block must not be echoed - while the good one is still answered. Echoing
        both is what caused ParamValidationError even after the all-malformed case was
        handled.
        """
        response = {
            "output": {
                "message": {
                    "content": [
                        {"text": "Ich suche."},
                        {"toolUse": {"toolUseId": "tu-1", "name": "search_layers", "input": {}}},
                        {"toolUse": {"input": {}}},
                    ]
                }
            },
            "stopReason": "tool_use",
        }
        result = _parse_response(HANDLE, response)

        assert result.malformed_tool_uses == 1
        assert [u.name for u in result.tool_uses] == ["search_layers"]
        echoed = result.assistant_message["content"]
        assert len(echoed) == 2, "the unusable block must not be echoed"
        tool_blocks = [b for b in echoed if "toolUse" in b]
        assert len(tool_blocks) == len(result.tool_uses), "one echoed block per answerable call"
        assert all(b["toolUse"].get("toolUseId") for b in tool_blocks)

    def test_tool_use_without_input_yields_empty_arguments(self) -> None:
        response = {
            "output": {"message": {"content": [{"toolUse": {"toolUseId": "t", "name": "compute"}}]}}
        }
        result = _parse_response(HANDLE, response)
        assert result.tool_uses[0].arguments == {}


class TestFallback:
    def test_resolves_explicit_model_roles(self, settings: Settings) -> None:
        models = BedrockModels(settings)
        assert models.handle_for_role("primary") == models.handles[0]
        assert models.handle_for_role("secondary") == models.handles[1]

    async def test_prefers_the_primary_model(self, settings: Settings) -> None:
        primary = FakeBedrockClient(_text_response("from claude"))
        secondary = FakeBedrockClient(_text_response("from mistral"))
        models = _models(settings, {"eu-central-1": primary, "eu-west-1": secondary})

        result = await models.converse_with_fallback(messages=[], system="s")
        assert result.text == "from claude"
        assert secondary.calls == []

    async def test_access_denied_falls_back_and_is_remembered(self, settings: Settings) -> None:
        """The pilot's live condition: an org SCP denies Claude, Mistral serves."""
        primary = FakeBedrockClient(_client_error("AccessDeniedException"))
        secondary = FakeBedrockClient(_text_response("from mistral"))
        models = _models(settings, {"eu-central-1": primary, "eu-west-1": secondary})

        first = await models.converse_with_fallback(messages=[], system="s")
        assert first.text == "from mistral"
        assert [h.model_id for h in models.usable_handles] == ["test.secondary"]

        await models.converse_with_fallback(messages=[], system="s")
        # The blocked model is not retried on every turn.
        assert len(primary.calls) == 1

    async def test_a_malformed_request_does_not_disable_the_model(self, settings: Settings) -> None:
        """ValidationException means our request was wrong, not that Claude is blocked -
        disabling it would silently drop the primary model for the whole process."""
        primary = FakeBedrockClient(_client_error("ValidationException"))
        secondary = FakeBedrockClient(_text_response("from mistral"))
        models = _models(settings, {"eu-central-1": primary, "eu-west-1": secondary})

        await models.converse_with_fallback(messages=[], system="s")
        assert [h.model_id for h in models.usable_handles] == ["test.primary", "test.secondary"]

    async def test_every_model_failing_raises(self, settings: Settings) -> None:
        clients = {
            "eu-central-1": FakeBedrockClient(_client_error("AccessDeniedException")),
            "eu-west-1": FakeBedrockClient(_client_error("AccessDeniedException")),
        }
        models = _models(settings, clients)
        with pytest.raises(NoModelAvailable):
            await models.converse_with_fallback(messages=[], system="s")

    async def test_no_configured_model_raises(self) -> None:
        models = BedrockModels(Settings())
        with pytest.raises(NoModelAvailable):
            await models.converse_with_fallback(messages=[], system="s")

    async def test_a_pinned_handle_keeps_a_multi_step_turn_on_one_model(
        self, settings: Settings
    ) -> None:
        """Handing one model's tool_use blocks to another would be rejected."""
        primary = FakeBedrockClient(_client_error("ThrottlingException"))
        secondary = FakeBedrockClient(_text_response("from mistral"))
        models = _models(settings, {"eu-central-1": primary, "eu-west-1": secondary})

        with pytest.raises(NoModelAvailable):
            await models.converse_with_fallback(messages=[], system="s", pinned=models.handles[0])
        assert secondary.calls == []

    async def test_secondary_region_defaults_to_the_primary_region(self) -> None:
        settings = Settings(
            bedrock_primary_model_id="a",
            bedrock_secondary_model_id="b",
            bedrock_region="eu-central-1",
        )
        models = BedrockModels(settings)
        assert [h.region for h in models.handles] == ["eu-central-1", "eu-central-1"]

    async def test_tools_are_only_sent_when_present(self, settings: Settings) -> None:
        client = FakeBedrockClient(_text_response("ok"))
        models = _models(settings, {"eu-central-1": client})

        await models.converse_with_fallback(messages=[], system="s", tools=None)
        assert "toolConfig" not in client.calls[0]

        await models.converse_with_fallback(
            messages=[], system="s", tools=[{"toolSpec": {"name": "t"}}]
        )
        assert client.calls[1]["toolConfig"] == {"tools": [{"toolSpec": {"name": "t"}}]}


def test_tool_results_go_back_in_one_message() -> None:
    """Bedrock requires a toolResult for every toolUse block, in a single message."""
    blocks = [tool_result_block("a", "{}"), tool_result_block("b", "boom", is_error=True)]
    message = tool_results_message(blocks)
    assert message["role"] == "user"
    assert len(message["content"]) == 2
    assert message["content"][0]["toolResult"]["status"] == "success"
    assert message["content"][1]["toolResult"]["status"] == "error"


def test_a_callable_system_prompt_is_rendered_per_model() -> None:
    primary = ModelHandle(
        model_id="eu.anthropic.claude-sonnet-4-6", region="eu-central-1", role="primary"
    )
    secondary = ModelHandle(
        model_id="mistral.ministral-3-14b-instruct", region="eu-west-1", role="secondary"
    )

    def per_model(handle: ModelHandle) -> str:
        return f"prompt for {handle.model_id}"

    assert resolve_system(per_model, primary) == "prompt for eu.anthropic.claude-sonnet-4-6"
    assert resolve_system(per_model, secondary) == "prompt for mistral.ministral-3-14b-instruct"
    assert resolve_system("plain", primary) == "plain"


async def test_the_fallback_model_receives_its_own_prompt(settings: Settings) -> None:
    """The prompt is rendered per attempt, so a turn that falls back is not sent the
    blocked model's prompt."""
    primary = FakeBedrockClient(_client_error("AccessDeniedException"))
    secondary = FakeBedrockClient(_text_response("from mistral"))
    models = _models(settings, {"eu-central-1": primary, "eu-west-1": secondary})

    await models.converse_with_fallback(messages=[], system=lambda h: f"prompt::{h.model_id}")

    assert primary.calls[0]["system"] == [{"text": "prompt::test.primary"}]
    assert secondary.calls[0]["system"] == [{"text": "prompt::test.secondary"}]
