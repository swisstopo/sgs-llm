"""The agent loop: one user message in, a stream of protocol v1 events out.

Yields zero or more `intermediate` events then exactly one `final` or `error`. The
terminating `done` belongs to the transport (app/ws.py), so a failure here cannot produce
two terminal events.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any

from .. import i18n
from ..config import Settings
from ..mcp.client import ToolGateway
from ..protocol import (
    BBox,
    CatalogLayerRef,
    Error,
    Final,
    HistoryEntry,
    Intermediate,
    LayerSpec,
    ProtocolLang,
    ServerEvent,
    UserMessage,
)
from .bedrock import (
    BedrockModels,
    ModelHandle,
    NoModelAvailable,
    tool_result_block,
    tool_results_message,
)
from .layers import extract_catalog_layers, extract_focus_bbox, extract_layers
from .prompts import NO_RASTER_DISPLAY_NOTE, NO_TOOLS_NOTE, system_prompt

logger = logging.getLogger(__name__)

THINKING_STEP = "s0"

RETRY_TOOL_CALL_NUDGE = (
    "That tool call was incomplete - it named no tool. Either call one of the available "
    "tools with its name and arguments, or answer directly."
)

FINAL_ANSWER_NUDGE = (
    "Answer now, in the user's language, using only the information you already have. "
    "Do not call any more tools. If something is still missing, say what you could not "
    "determine."
)


def _append_user_text(messages: list[dict[str, Any]], text: str) -> None:
    """Adds user-role text, merging into the previous turn if it is also user-role.

    Bedrock requires alternating roles, and the previous turn is often a toolResult
    message - which is user-role - so appending blindly would break the sequence.
    """
    if messages and messages[-1]["role"] == "user":
        messages[-1]["content"].append({"text": text})
    else:
        messages.append({"role": "user", "content": [{"text": text}]})


@dataclass
class TurnStats:
    """Everything about a turn that the protocol does not carry but the
    conversation log wants (docs/deployment.md#what-gets-stored)."""

    model_id: str = ""
    tool_calls: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    layer_count: int = 0
    markdown: str = ""
    error_code: str | None = None


def build_messages(
    history: list[HistoryEntry], content: str, *, limit: int
) -> list[dict[str, Any]]:
    """Converts protocol history into a Bedrock message list.

    Bedrock requires the conversation to start with a user turn and to alternate
    roles. The frontend's history is already ordered, but it is truncated to a fixed
    window (ChatService.buildHistory), so it can begin mid-exchange with an assistant
    turn - that entry is dropped, and consecutive same-role entries are merged.
    """
    messages: list[dict[str, Any]] = []
    for entry in history[-limit:]:
        text = entry.content.strip()
        if not text:
            continue
        if not messages and entry.role != "user":
            continue
        if messages and messages[-1]["role"] == entry.role:
            messages[-1]["content"][0]["text"] += "\n\n" + text
            continue
        messages.append({"role": entry.role, "content": [{"text": text}]})

    current = content.strip() or "(empty message)"
    if messages and messages[-1]["role"] == "user":
        messages[-1]["content"][0]["text"] += "\n\n" + current
    else:
        messages.append({"role": "user", "content": [{"text": current}]})
    return messages


async def run_turn(
    message: UserMessage,
    *,
    models: BedrockModels,
    gateway: ToolGateway,
    settings: Settings,
    stats: TurnStats,
    base_url: str = "",
) -> AsyncGenerator[ServerEvent, None]:
    lang: ProtocolLang = message.language
    message_id = message.id
    messages = build_messages(message.history, message.content, limit=settings.max_history_entries)
    layers: list[LayerSpec] = []
    layer_index = 0
    catalog_layers: list[CatalogLayerRef] = []
    focus_bbox: BBox | None = None

    yield Intermediate(
        message_id=message_id, step_id=THINKING_STEP, status="started", label=i18n.thinking(lang)
    )

    async with gateway.session() as tools:
        # Rendered per attempt rather than once, so a turn that falls back to the
        # secondary model gets that model's prompt (app/agent/prompts.py).
        def prompt(handle: ModelHandle) -> str:
            text = system_prompt(lang, message.map_context, model_id=handle.model_id)
            if not tools.tool_specs:
                return text + NO_TOOLS_NOTE
            if not settings.enable_catalog_layers:
                text += NO_RASTER_DISPLAY_NOTE
            return text

        pinned: ModelHandle | None = None
        last_text = ""
        thinking_closed = False
        step = 0

        for iteration in range(settings.max_tool_iterations):
            # The tool set must NOT be withdrawn to stop a model that keeps calling
            # tools: once the conversation holds toolUse or toolResult blocks, Bedrock
            # rejects a request carrying no toolConfig with ValidationException. Steering
            # with an instruction keeps it valid.
            last_iteration = iteration == settings.max_tool_iterations - 1
            if last_iteration and messages:
                _append_user_text(messages, FINAL_ANSWER_NUDGE)

            try:
                result = await models.converse_with_fallback(
                    messages=messages,
                    system=prompt,
                    tools=tools.tool_specs or None,
                    pinned=pinned,
                )
            except NoModelAvailable:
                logger.error("no Bedrock model could serve message %s", message_id)
                stats.error_code = "internal"
                if not thinking_closed:
                    yield Intermediate(
                        message_id=message_id,
                        step_id=THINKING_STEP,
                        status="failed",
                        label=i18n.tool_failed(lang),
                    )
                yield Error(message_id=message_id, code="internal", message=i18n.internal(lang))
                return

            pinned = result.handle
            last_text = result.text or last_text
            stats.model_id = str(result.handle)
            stats.input_tokens += result.input_tokens
            stats.output_tokens += result.output_tokens

            if not thinking_closed:
                thinking_closed = True
                yield Intermediate(
                    message_id=message_id,
                    step_id=THINKING_STEP,
                    status="finished",
                    label=i18n.thinking(lang),
                )

            if not result.tool_uses and result.malformed_tool_uses and not last_iteration:
                # No callable tool named. The turn cannot be echoed back, so it is
                # dropped and the model asked again.
                logger.warning("%s emitted only unusable tool calls; retrying", result.handle)
                _append_user_text(messages, RETRY_TOOL_CALL_NUDGE)
                continue

            if not result.tool_uses:
                text = result.text
                if not text:
                    logger.warning(
                        "model %s produced no text (stop_reason=%s)",
                        result.handle,
                        result.stop_reason,
                    )
                    stats.error_code = "internal"
                    yield Error(message_id=message_id, code="internal", message=i18n.internal(lang))
                    return
                stats.markdown = text
                stats.layer_count = len(layers) + len(catalog_layers)
                yield Final(
                    message_id=message_id,
                    content_markdown=text,
                    layers=layers or None,
                    catalog_layers=catalog_layers or None,
                    focus_bbox=focus_bbox,
                )
                return

            messages.append(result.assistant_message)
            blocks: list[dict[str, Any]] = []
            for use in result.tool_uses:
                step += 1
                step_id = f"t{step}"
                yield Intermediate(
                    message_id=message_id,
                    step_id=step_id,
                    status="started",
                    label=i18n.tool_running(use.name, lang),
                )

                outcome = await tools.call(use.name, use.arguments)
                stats.tool_calls.append(use.name)
                blocks.append(
                    tool_result_block(use.tool_use_id, outcome.text, is_error=outcome.is_error)
                )

                if outcome.is_error:
                    yield Intermediate(
                        message_id=message_id,
                        step_id=step_id,
                        status="failed",
                        label=i18n.tool_failed(lang),
                        detail=outcome.text[:400],
                    )
                    continue

                found = extract_layers(outcome.data, base_url=base_url, start_index=layer_index)
                layer_index += len(found)
                for spec in found:
                    if all(spec.url != existing.url for existing in layers):
                        layers.append(spec)

                if settings.enable_catalog_layers:
                    for ref in extract_catalog_layers(outcome.data):
                        if all(ref.id != existing.id for existing in catalog_layers):
                            catalog_layers.append(ref)
                    focus_bbox = extract_focus_bbox(outcome.data) or focus_bbox

                yield Intermediate(
                    message_id=message_id,
                    step_id=step_id,
                    status="finished",
                    label=i18n.tool_running(use.name, lang),
                )

            messages.append(tool_results_message(blocks))

    # Reaching here means every iteration asked for another tool call, which
    # FINAL_ANSWER_NUDGE should have prevented. Whatever the model last said, plus any
    # layers already produced, is a better answer than discarding the turn.
    logger.error("agent loop exhausted without an answer for %s", message_id)
    if last_text:
        stats.markdown = last_text
        stats.layer_count = len(layers) + len(catalog_layers)
        yield Final(
            message_id=message_id,
            content_markdown=last_text,
            layers=layers or None,
            catalog_layers=catalog_layers or None,
            focus_bbox=focus_bbox,
        )
        return
    stats.error_code = "internal"
    yield Error(message_id=message_id, code="internal", message=i18n.internal(lang))
