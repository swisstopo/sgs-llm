"""Apertus 1.5 over its self-hosted OpenAI-compatible endpoint (docs/apertus-endpoint.md)."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from ..config import Settings
from .models import ConverseResult, ModelHandle, SystemPrompt, ToolUse, resolve_system

logger = logging.getLogger(__name__)

# vLLM binds its port before the model is ready, and a morning start takes ~5 minutes.
_OFFLINE_STATUS = frozenset({502, 503, 504})

_STOP_REASONS = {
    "stop": "end_turn",
    "tool_calls": "tool_use",
    "length": "max_tokens",
    "content_filter": "content_filtered",
}


def openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Converse `toolConfig.tools` as OpenAI `tools`."""
    converted: list[dict[str, Any]] = []
    for entry in tools:
        spec = entry.get("toolSpec")
        if not isinstance(spec, dict):
            continue
        converted.append(
            {
                "type": "function",
                "function": {
                    "name": spec.get("name", ""),
                    "description": spec.get("description", ""),
                    "parameters": spec.get("inputSchema", {}).get("json", {}),
                },
            }
        )
    return converted


def openai_messages(messages: list[dict[str, Any]], system: str) -> list[dict[str, Any]]:
    """The internal Converse-shaped conversation as OpenAI chat messages.

    One Converse message can become several: tool results arrive batched in a single
    user-role message (Bedrock requires that), while OpenAI wants one `tool` message per
    result. They are emitted before any text from the same turn, because a `tool` message
    must follow the assistant turn that called it.
    """
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]

    for message in messages:
        role = message.get("role")
        texts: list[str] = []
        tool_calls: list[dict[str, Any]] = []

        for block in message.get("content", []) or []:
            if not isinstance(block, dict):
                continue
            if isinstance(block.get("text"), str):
                texts.append(block["text"])
            tool_use = block.get("toolUse")
            if isinstance(tool_use, dict):
                tool_calls.append(
                    {
                        "id": tool_use.get("toolUseId", ""),
                        "type": "function",
                        "function": {
                            "name": tool_use.get("name", ""),
                            "arguments": json.dumps(tool_use.get("input") or {}),
                        },
                    }
                )
            tool_result = block.get("toolResult")
            if isinstance(tool_result, dict):
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_result.get("toolUseId", ""),
                        "content": _tool_result_text(tool_result),
                    }
                )

        text = "\n\n".join(texts)
        if role == "assistant":
            if text or tool_calls:
                assistant: dict[str, Any] = {"role": "assistant", "content": text or None}
                if tool_calls:
                    assistant["tool_calls"] = tool_calls
                out.append(assistant)
        elif text:
            out.append({"role": "user", "content": text})

    return out


def _tool_result_text(tool_result: dict[str, Any]) -> str:
    parts = [
        block["text"]
        for block in tool_result.get("content", []) or []
        if isinstance(block, dict) and isinstance(block.get("text"), str)
    ]
    return "\n".join(parts)


def parse_openai_response(handle: ModelHandle, response: dict[str, Any]) -> ConverseResult:
    """One chat completion as the internal Converse-shaped result.

    `assistant_message` is rebuilt in the internal shape rather than kept as returned, so
    the loop's echo logic and app/agent/bedrock.py's stay identical - openai_messages()
    translates it back on the next call.
    """
    choices = response.get("choices") or []
    choice = choices[0] if choices and isinstance(choices[0], dict) else {}
    message = choice.get("message") or {}

    text = message.get("content")
    text = text.strip() if isinstance(text, str) else ""

    tool_uses: list[ToolUse] = []
    kept: list[dict[str, Any]] = []
    malformed = 0

    if text:
        kept.append({"text": text})

    for call in message.get("tool_calls") or []:
        if not isinstance(call, dict):
            malformed += 1
            continue
        function = call.get("function") or {}
        tool_use_id = str(call.get("id") or "")
        name = str(function.get("name") or "")
        arguments = _tool_arguments(function.get("arguments"))
        # Same rule as the Bedrock path: a block that cannot be answered must not be
        # echoed, because every echoed tool call needs a matching result.
        if not tool_use_id or not name or arguments is None:
            malformed += 1
            continue
        tool_uses.append(ToolUse(tool_use_id=tool_use_id, name=name, arguments=arguments))
        kept.append({"toolUse": {"toolUseId": tool_use_id, "name": name, "input": arguments}})

    if malformed:
        logger.warning(
            "%s returned %d unusable tool call(s); dropped from the echoed turn",
            handle,
            malformed,
        )

    usage = response.get("usage") or {}
    return ConverseResult(
        handle=handle,
        stop_reason=_STOP_REASONS.get(str(choice.get("finish_reason") or ""), "end_turn"),
        text=text,
        tool_uses=tool_uses,
        assistant_message={"role": "assistant", "content": kept},
        malformed_tool_uses=malformed,
        input_tokens=int(usage.get("prompt_tokens", 0) or 0),
        output_tokens=int(usage.get("completion_tokens", 0) or 0),
    )


def _tool_arguments(raw: Any) -> dict[str, Any] | None:
    """Arguments arrive as a JSON *string*. None means the model emitted something unusable."""
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


class ApertusOffline(RuntimeError):
    """The endpoint is not accepting connections. Expected outside office hours."""


class ApertusProvider:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: Any | None = None

    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            # A short connect timeout because a closed endpoint is the normal overnight
            # state and should fail fast; a long read timeout because 16.8 tok/s means a
            # 400-token answer takes ~24 s (docs/apertus-endpoint.md).
            self._client = httpx.AsyncClient(
                timeout=httpx.Timeout(
                    connect=5.0,
                    read=max(30.0, self._settings.apertus_turn_timeout_seconds - 10.0),
                    write=10.0,
                    pool=5.0,
                )
            )
        return self._client

    async def converse(
        self,
        handle: ModelHandle,
        *,
        messages: list[dict[str, Any]],
        system: SystemPrompt,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 2048,
    ) -> ConverseResult:
        """One chat completion. Raises ApertusOffline when the endpoint is not there."""
        payload: dict[str, Any] = {
            "model": handle.model_id,
            "messages": openai_messages(messages, resolve_system(system, handle)),
            "max_tokens": max_tokens,
            "temperature": 0.2,
        }
        if tools:
            # Absent rather than [], which vLLM rejects.
            payload["tools"] = openai_tools(tools)

        url = f"{self._settings.apertus_base_url.rstrip('/')}/chat/completions"
        headers = {"Authorization": f"Bearer {self._settings.apertus_api_key}"}

        try:
            response = await self._http().post(url, json=payload, headers=headers)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise ApertusOffline(f"{handle} is not accepting connections") from exc

        if response.status_code in _OFFLINE_STATUS:
            raise ApertusOffline(f"{handle} returned {response.status_code}")
        if response.status_code >= 400:
            # The body carries the whole diagnosis for a context overflow, which is the
            # failure this endpoint is most likely to produce.
            logger.error(
                "%s rejected the request (%s): %s",
                handle,
                response.status_code,
                _detail(response),
            )
            response.raise_for_status()

        return parse_openai_response(handle, response.json())


def _detail(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:500]
    if isinstance(body, dict):
        error = body.get("error")
        if isinstance(error, dict):
            message = error.get("message")
            if isinstance(message, str):
                return message
    return response.text[:500]
