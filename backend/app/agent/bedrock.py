"""Bedrock access over the Converse API (docs/llm.md).

Both pilot models share one code path and differ only in id and region: Claude goes
through an EU inference profile in BEDROCK_REGION, the pilot's Mistral is in-region in
eu-west-1 only. Claude is tried first; an organization SCP currently denies it, so a
denial is expected and the secondary serves instead.

Credentials come from the normal boto3 chain, so the task role and a workstation's
AWS_BEARER_TOKEN_BEDROCK both work.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Union

from ..config import Settings

logger = logging.getLogger(__name__)

ModelRole = Literal["primary", "secondary"]

# A callable is rendered per attempt, so under fallback the model that serves the turn gets
# its own prompt (app/agent/prompts.py).
SystemPrompt = Union[str, "Callable[[ModelHandle], str]"]

# ValidationException is excluded: it means our request was malformed, not that the model
# is unavailable, and it would otherwise disable the primary for the whole process.
_UNAVAILABLE_ERRORS = frozenset({"AccessDeniedException", "ResourceNotFoundException"})


@dataclass(frozen=True)
class ModelHandle:
    model_id: str
    region: str
    role: ModelRole

    def __str__(self) -> str:
        return f"{self.model_id}@{self.region}"


class NoModelAvailable(RuntimeError):
    """Every configured model refused the request."""


def resolve_system(system: SystemPrompt, handle: ModelHandle) -> str:
    return system(handle) if callable(system) else system


@dataclass
class ToolUse:
    tool_use_id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class ConverseResult:
    handle: ModelHandle
    stop_reason: str
    text: str
    tool_uses: list[ToolUse] = field(default_factory=list)
    # The assistant message exactly as returned, to be appended to the running
    # conversation. Bedrock requires the tool_use blocks be echoed back verbatim.
    assistant_message: dict[str, Any] = field(default_factory=dict)
    # Blocks with no name or id. Bedrock demands one toolResult per block in the echoed
    # turn, and an unidentifiable block cannot be answered.
    malformed_tool_uses: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


def _error_code(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code")
        if isinstance(code, str):
            return code
    return type(exc).__name__


class BedrockModels:
    """Resolves and invokes the configured models, newest-preferred first."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._clients: dict[str, Any] = {}
        self._unavailable: set[str] = set()

    @property
    def handles(self) -> tuple[ModelHandle, ...]:
        """Configured models in preference order, skipping unset ids."""
        candidates: list[ModelHandle] = []
        if self._settings.bedrock_primary_model_id:
            candidates.append(
                ModelHandle(
                    model_id=self._settings.bedrock_primary_model_id,
                    region=self._settings.bedrock_region,
                    role="primary",
                )
            )
        if self._settings.bedrock_secondary_model_id:
            candidates.append(
                ModelHandle(
                    model_id=self._settings.bedrock_secondary_model_id,
                    region=self._settings.secondary_region,
                    role="secondary",
                )
            )
        return tuple(candidates)

    @property
    def usable_handles(self) -> tuple[ModelHandle, ...]:
        return tuple(h for h in self.handles if h.model_id not in self._unavailable)

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
        return _parse_response(handle, response)

    async def converse_with_fallback(
        self,
        *,
        messages: list[dict[str, Any]],
        system: SystemPrompt,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int = 2048,
        pinned: ModelHandle | None = None,
    ) -> ConverseResult:
        """Tries each usable model in order until one answers.

        `pinned` keeps a multi-step turn on the model that started it - switching
        models mid-tool-loop would hand one model's tool_use blocks to another.
        """
        candidates = (pinned,) if pinned is not None else self.usable_handles
        if not candidates:
            raise NoModelAvailable("no Bedrock model is configured")

        last_error: Exception | None = None
        for handle in candidates:
            if handle is None:
                continue
            try:
                return await self.converse(
                    handle, messages=messages, system=system, tools=tools, max_tokens=max_tokens
                )
            except Exception as exc:
                code = _error_code(exc)
                last_error = exc
                if code in _UNAVAILABLE_ERRORS:
                    if handle.model_id not in self._unavailable:
                        self._unavailable.add(handle.model_id)
                        logger.warning(
                            "model %s unavailable (%s); falling back. This is expected for "
                            "Claude until organization SCP p-ddxnpgbm is amended (docs/llm.md)",
                            handle,
                            code,
                        )
                    continue
                logger.warning("model %s failed with %s", handle, code)
                continue

        raise NoModelAvailable("every configured model refused the request") from last_error


def _parse_response(handle: ModelHandle, response: dict[str, Any]) -> ConverseResult:
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


def tool_result_block(tool_use_id: str, payload: str, *, is_error: bool = False) -> dict[str, Any]:
    """One tool's output, as a content block."""
    return {
        "toolResult": {
            "toolUseId": tool_use_id,
            "content": [{"text": payload}],
            "status": "error" if is_error else "success",
        }
    }


def tool_results_message(blocks: list[dict[str, Any]]) -> dict[str, Any]:
    """Carries tool output back to the model.

    All blocks go in one message. When a response contains several tool_use blocks,
    Bedrock requires a toolResult for each before it accepts the conversation, and
    rejects them answered one message at a time.
    """
    return {"role": "user", "content": blocks}
