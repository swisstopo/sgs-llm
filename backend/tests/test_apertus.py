"""The OpenAI-compatible provider: translation both ways, and offline behaviour.

Apertus is self-hosted on a weekday office-hours schedule (docs/apertus-endpoint.md), so
"the endpoint is not there" is normal operation rather than an incident, and the tests
below pin what the backend does about it.
"""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from app.agent.apertus import (
    ApertusOffline,
    ApertusProvider,
    openai_messages,
    openai_tools,
    parse_openai_response,
)
from app.agent.models import ModelHandle, configured_model_handle, tool_result_block
from app.agent.router import ModelRouter
from app.config import Settings
from tests.conftest import HANDLE

APERTUS_HANDLE = ModelHandle(
    model_id="apertus-8b", region="eu-central-1", role="apertus", provider="openai"
)


class TestToolTranslation:
    def test_converts_a_converse_tool_spec_to_an_openai_function(self) -> None:
        schema = {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        }
        converse = [
            {
                "toolSpec": {
                    "name": "search_layers",
                    "description": "Find geodata layers.",
                    "inputSchema": {"json": schema},
                }
            }
        ]

        assert openai_tools(converse) == [
            {
                "type": "function",
                "function": {
                    "name": "search_layers",
                    "description": "Find geodata layers.",
                    "parameters": schema,
                },
            }
        ]


class TestMessageTranslation:
    def test_puts_the_system_prompt_first(self) -> None:
        messages = openai_messages([{"role": "user", "content": [{"text": "Grüezi"}]}], "be brief")

        assert messages == [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "Grüezi"},
        ]

    def test_joins_several_text_blocks_in_one_turn(self) -> None:
        converse = [{"role": "user", "content": [{"text": "first"}, {"text": "second"}]}]

        assert openai_messages(converse, "s")[1] == {"role": "user", "content": "first\n\nsecond"}

    def test_renders_a_tool_call_with_arguments_as_a_json_string(self) -> None:
        converse = [
            {
                "role": "assistant",
                "content": [
                    {"toolUse": {"toolUseId": "tu1", "name": "search_layers", "input": {"q": "x"}}}
                ],
            }
        ]

        assert openai_messages(converse, "s")[1] == {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "tu1",
                    "type": "function",
                    "function": {"name": "search_layers", "arguments": '{"q": "x"}'},
                }
            ],
        }

    def test_turns_each_tool_result_into_its_own_tool_message(self) -> None:
        converse = [
            {
                "role": "user",
                "content": [
                    tool_result_block("tu1", "one"),
                    tool_result_block("tu2", "two", is_error=True),
                ],
            }
        ]

        assert openai_messages(converse, "s")[1:] == [
            {"role": "tool", "tool_call_id": "tu1", "content": "one"},
            {"role": "tool", "tool_call_id": "tu2", "content": "two"},
        ]

    def test_keeps_text_and_tool_calls_from_the_same_assistant_turn_together(self) -> None:
        converse = [
            {
                "role": "assistant",
                "content": [
                    {"text": "looking"},
                    {"toolUse": {"toolUseId": "tu1", "name": "t", "input": {}}},
                ],
            }
        ]

        assert openai_messages(converse, "s")[1] == {
            "role": "assistant",
            "content": "looking",
            "tool_calls": [
                {"id": "tu1", "type": "function", "function": {"name": "t", "arguments": "{}"}}
            ],
        }


def _response(message: dict[str, Any], finish_reason: str = "stop") -> dict[str, Any]:
    return {
        "choices": [{"message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 34},
    }


class TestResponseParsing:
    def test_extracts_text_and_usage(self) -> None:
        result = parse_openai_response(HANDLE, _response({"content": "  Hochwasser  "}))

        assert result.text == "Hochwasser"
        assert (result.input_tokens, result.output_tokens) == (120, 34)
        assert result.handle is HANDLE

    def test_maps_finish_reason_onto_the_converse_vocabulary(self) -> None:
        reasons = {"stop": "end_turn", "tool_calls": "tool_use", "length": "max_tokens"}

        for openai_reason, converse_reason in reasons.items():
            result = parse_openai_response(HANDLE, _response({"content": "x"}, openai_reason))
            assert result.stop_reason == converse_reason

    def test_parses_a_tool_call_and_its_json_arguments(self) -> None:
        message = {
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "function": {"name": "search_layers", "arguments": '{"q": "Wallis"}'},
                }
            ],
        }

        result = parse_openai_response(HANDLE, _response(message, "tool_calls"))

        assert len(result.tool_uses) == 1
        assert result.tool_uses[0].tool_use_id == "call_1"
        assert result.tool_uses[0].name == "search_layers"
        assert result.tool_uses[0].arguments == {"q": "Wallis"}

    def test_echoes_the_assistant_turn_in_the_internal_converse_shape(self) -> None:
        """The loop appends this verbatim, so it has to survive a round trip."""
        message = {
            "content": "looking",
            "tool_calls": [{"id": "call_1", "function": {"name": "t", "arguments": '{"a": 1}'}}],
        }

        result = parse_openai_response(HANDLE, _response(message, "tool_calls"))

        assert result.assistant_message == {
            "role": "assistant",
            "content": [
                {"text": "looking"},
                {"toolUse": {"toolUseId": "call_1", "name": "t", "input": {"a": 1}}},
            ],
        }
        assert openai_messages([result.assistant_message], "s")[1] == {
            "role": "assistant",
            "content": "looking",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "t", "arguments": '{"a": 1}'},
                }
            ],
        }

    def test_counts_a_tool_call_with_unparseable_arguments_as_malformed(self) -> None:
        message = {"tool_calls": [{"id": "c1", "function": {"name": "t", "arguments": "{oops"}}]}

        result = parse_openai_response(HANDLE, _response(message, "tool_calls"))

        assert result.tool_uses == []
        assert result.malformed_tool_uses == 1

    def test_counts_a_tool_call_with_no_name_as_malformed(self) -> None:
        message = {"tool_calls": [{"id": "c1", "function": {"name": "", "arguments": "{}"}}]}

        result = parse_openai_response(HANDLE, _response(message, "tool_calls"))

        assert result.tool_uses == []
        assert result.malformed_tool_uses == 1

    def test_drops_a_malformed_call_from_the_echoed_turn(self) -> None:
        """An unanswerable block must not be echoed, or the next request cannot be built."""
        message = {
            "tool_calls": [
                {"id": "good", "function": {"name": "t", "arguments": "{}"}},
                {"id": "bad", "function": {"name": "t", "arguments": "{oops"}},
            ]
        }

        result = parse_openai_response(HANDLE, _response(message, "tool_calls"))

        echoed = [block["toolUse"]["toolUseId"] for block in result.assistant_message["content"]]
        assert echoed == ["good"]


def _provider(handler: Any, settings: Settings | None = None) -> ApertusProvider:
    """A provider whose HTTP goes to `handler` - real httpx, real request building."""
    provider = ApertusProvider(settings or _settings())
    provider._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return provider


def _settings(**overrides: Any) -> Settings:
    return Settings(
        apertus_base_url="http://10.0.0.1:8000/v1",
        apertus_api_key="k",
        apertus_model_id="apertus-8b",
        **overrides,
    )


def _ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200, json=_response({"content": "Grüezi"}))


class TestProviderRequest:
    async def test_posts_a_chat_completion_with_the_bearer_key(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return _ok(request)

        result = await _provider(handler).converse(
            APERTUS_HANDLE,
            messages=[{"role": "user", "content": [{"text": "Hoi"}]}],
            system="be brief",
            tools=[{"toolSpec": {"name": "t", "description": "d", "inputSchema": {"json": {}}}}],
            max_tokens=512,
        )

        assert result.text == "Grüezi"
        assert len(seen) == 1
        assert str(seen[0].url) == "http://10.0.0.1:8000/v1/chat/completions"
        assert seen[0].headers["authorization"] == "Bearer k"

        body = json.loads(seen[0].content)
        assert body["model"] == "apertus-8b"
        assert body["max_tokens"] == 512
        assert body["messages"][0] == {"role": "system", "content": "be brief"}
        assert body["tools"][0]["function"]["name"] == "t"

    async def test_omits_tools_when_there_are_none(self) -> None:
        """vLLM rejects an empty tools array, so the key must be absent rather than []."""
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return _ok(request)

        await _provider(handler).converse(
            APERTUS_HANDLE, messages=[], system="s", tools=None, max_tokens=10
        )

        assert "tools" not in json.loads(seen[0].content)


class TestOffline:
    async def test_a_refused_connection_is_reported_as_offline(self) -> None:
        """Nightly and weekend downtime is normal operation (docs/apertus-endpoint.md)."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("connection refused", request=request)

        with pytest.raises(ApertusOffline):
            await _provider(handler).converse(APERTUS_HANDLE, messages=[], system="s")

    async def test_a_connect_timeout_is_reported_as_offline(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectTimeout("timed out", request=request)

        with pytest.raises(ApertusOffline):
            await _provider(handler).converse(APERTUS_HANDLE, messages=[], system="s")

    async def test_service_unavailable_while_vllm_loads_is_offline(self) -> None:
        """A morning start takes ~5 minutes; the port opens before the model serves."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(503, text="model is loading")

        with pytest.raises(ApertusOffline):
            await _provider(handler).converse(APERTUS_HANDLE, messages=[], system="s")

    async def test_a_rejected_key_is_not_offline(self) -> None:
        """A bad key is a misconfiguration - reporting it as downtime would hide it."""

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, text="Unauthorized")

        with pytest.raises(httpx.HTTPStatusError):
            await _provider(handler).converse(APERTUS_HANDLE, messages=[], system="s")

    async def test_a_context_overflow_is_not_offline_and_is_logged_verbatim(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The vLLM message names both halves of the budget; it is the whole diagnosis."""
        detail = (
            "This model's maximum context length is 28000 tokens. However, you requested "
            "29000 tokens (26952 in the messages, 2048 in the completion)."
        )

        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(400, json={"error": {"message": detail}})

        with caplog.at_level("ERROR"), pytest.raises(httpx.HTTPStatusError):
            await _provider(handler).converse(APERTUS_HANDLE, messages=[], system="s")

        assert detail in caplog.text


class TestRouting:
    def test_resolves_the_apertus_role_to_the_openai_provider(self) -> None:
        handle = configured_model_handle(_settings(), "apertus")

        assert handle == ModelHandle(
            model_id="apertus-8b", region="eu-central-1", role="apertus", provider="openai"
        )

    def test_an_unset_base_url_leaves_the_role_unconfigured(self) -> None:
        """The deployed default is off, and CI smoke-tests the image with nothing set."""
        assert configured_model_handle(Settings(), "apertus") is None

    def test_lists_apertus_among_the_configured_models(self) -> None:
        settings = _settings(bedrock_primary_model_id="eu.anthropic.claude-sonnet-4-6")

        roles = [handle.role for handle in ModelRouter(settings).handles]

        assert roles == ["primary", "apertus"]

    def test_an_unpinned_turn_never_lands_on_apertus(self) -> None:
        """Self-hosted and explicit-only: a Claude request must not silently be answered
        by Apertus, which is a different model with a different residency story."""
        settings = _settings(bedrock_primary_model_id="eu.anthropic.claude-sonnet-4-6")

        candidates = [handle.role for handle in ModelRouter(settings).fallback_candidates]

        assert candidates == ["primary"]

    async def test_dispatches_an_openai_handle_to_the_apertus_provider(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return _ok(request)

        router = ModelRouter(_settings())
        router._apertus._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        result = await router.converse(APERTUS_HANDLE, messages=[], system="s")

        assert result.text == "Grüezi"
        assert len(seen) == 1

    async def test_uses_the_apertus_token_budget_rather_than_the_bedrock_default(self) -> None:
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return _ok(request)

        router = ModelRouter(_settings(apertus_max_tokens=768))
        router._apertus._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        await router.converse(APERTUS_HANDLE, messages=[], system="s")

        assert json.loads(seen[0].content)["max_tokens"] == 768

    async def test_offline_does_not_disable_apertus_for_the_process(self) -> None:
        """`_unavailable` is process-lifetime and correct for an SCP deny. Apertus comes
        back at 06:30, so caching it dead would keep it dead until the task is replaced."""
        attempts: list[int] = []

        def handler(request: httpx.Request) -> httpx.Response:
            attempts.append(1)
            raise httpx.ConnectError("refused", request=request)

        router = ModelRouter(_settings())
        router._apertus._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        for _ in range(2):
            with pytest.raises(ApertusOffline):
                await router.converse_with_fallback(messages=[], system="s", pinned=APERTUS_HANDLE)

        assert len(attempts) == 2
        assert router.usable_handles == router.handles

    async def test_a_pinned_apertus_turn_is_not_served_by_bedrock(self) -> None:
        """Chosen behaviour: a user who selected Apertus gets Apertus or an error."""

        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("refused", request=request)

        settings = _settings(bedrock_primary_model_id="eu.anthropic.claude-sonnet-4-6")
        router = ModelRouter(settings)
        router._apertus._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        with pytest.raises(ApertusOffline):
            await router.converse_with_fallback(messages=[], system="s", pinned=APERTUS_HANDLE)

    async def test_an_explicit_token_cap_wins_over_the_configured_default(self) -> None:
        """The judge call asks for 300. Silently spending 2048 would cost 1,748 tokens of
        input budget, which is what APERTUS_MAX_TOKENS exists to reclaim."""
        seen: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            seen.append(request)
            return _ok(request)

        router = ModelRouter(_settings(apertus_max_tokens=2048))
        router._apertus._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))

        await router.converse(APERTUS_HANDLE, messages=[], system="s", max_tokens=300)

        assert json.loads(seen[0].content)["max_tokens"] == 300
