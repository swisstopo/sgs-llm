"""Bedrock access over the Converse API (docs/llm.md).

Both Bedrock pilot models share one code path and differ only in id and region: Claude
goes through an EU inference profile in BEDROCK_REGION, the pilot's Mistral is in-region
in eu-west-1 only.

Credentials come from the normal boto3 chain, so the task role and a workstation's
AWS_BEARER_TOKEN_BEDROCK both work.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .models import (
    ConverseResult,
    ModelHandle,
    SystemPrompt,
    ToolUse,
    resolve_system,
)

logger = logging.getLogger(__name__)


class BedrockProvider:
    """Invokes Bedrock models. One client per region, created on first use."""

    def __init__(self) -> None:
        self._clients: dict[str, Any] = {}

    def _client(self, region: str) -> Any:
        if region not in self._clients:
            import boto3
            from botocore.config import Config

            self._clients[region] = boto3.client(
                "bedrock-runtime",
                region_name=region,
                config=Config(
                    connect_timeout=10,
                    read_timeout=120,
                    retries={"max_attempts": 3, "mode": "standard"},
                ),
            )
        return self._clients[region]

    async def converse(
        self,
        handle: ModelHandle,
        *,
        messages: list[dict[str, Any]],
        system: SystemPrompt,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 2048,
    ) -> ConverseResult:
        """One Converse turn against one model. Raises on any Bedrock error."""
        request: dict[str, Any] = {
            "modelId": handle.model_id,
            "messages": messages,
            "system": [{"text": resolve_system(system, handle)}],
            "inferenceConfig": {"maxTokens": max_tokens, "temperature": 0.2},
        }
        if tools:
            request["toolConfig"] = {"tools": tools}

        client = self._client(handle.region)
        response = await asyncio.to_thread(lambda: client.converse(**request))
        return parse_response(handle, response)


def parse_response(handle: ModelHandle, response: dict[str, Any]) -> ConverseResult:
    message = response.get("output", {}).get("message", {}) or {}
    blocks = message.get("content", []) or []

    texts: list[str] = []
    tool_uses: list[ToolUse] = []
    # Only the blocks that go back to Bedrock. A block we cannot answer must not be
    # echoed even when the same response also contains good ones; echoing a mixed response
    # whole still produced ParamValidationError.
    kept: list[dict[str, Any]] = []
    malformed = 0

    for block in blocks:
        if not isinstance(block, dict):
            continue
        if isinstance(block.get("text"), str):
            texts.append(block["text"])
        tool_use = block.get("toolUse")
        if isinstance(tool_use, dict):
            tool_use_id = str(tool_use.get("toolUseId") or "")
            name = str(tool_use.get("name") or "")
            if not tool_use_id or not name:
                # Observed from Mistral. Echoing one back sends an empty toolUseId, which
                # botocore rejects client-side and kills the turn. Counted so the caller
                # can recover.
                malformed += 1
                continue
            arguments = tool_use.get("input")
            tool_uses.append(
                ToolUse(
                    tool_use_id=tool_use_id,
                    name=name,
                    arguments=arguments if isinstance(arguments, dict) else {},
                )
            )
        kept.append(block)

    if malformed:
        logger.warning(
            "%s returned %d unusable toolUse block(s); dropped from the echoed turn",
            handle,
            malformed,
        )

    usage = response.get("usage", {}) or {}
    return ConverseResult(
        handle=handle,
        stop_reason=str(response.get("stopReason", "")),
        text="".join(texts).strip(),
        tool_uses=tool_uses,
        assistant_message={"role": "assistant", "content": kept},
        malformed_tool_uses=malformed,
        input_tokens=int(usage.get("inputTokens", 0) or 0),
        output_tokens=int(usage.get("outputTokens", 0) or 0),
    )
