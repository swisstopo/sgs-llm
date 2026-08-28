"""The model layer's internal contract, shared by every provider.

The internal message format is Bedrock Converse-shaped. That is a deliberate choice
rather than an accident of history: Converse is the strictest of the provider formats -
a tool_use block must be echoed back verbatim, and every one of them needs its own
toolResult before the conversation is accepted - so any looser format can be reached by
translating down from it. app/agent/apertus.py does exactly that for OpenAI-compatible
endpoints.

Types only. Providers import this; it imports no provider, which is what keeps
app/agent/router.py free to hold them all.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal, Union

from ..config import Settings

# "apertus" is a third UI-selectable role rather than a third Bedrock model: it is
# self-hosted behind an OpenAI-compatible endpoint (docs/apertus-endpoint.md).
ModelRole = Literal["primary", "secondary", "apertus"]
Provider = Literal["bedrock", "openai"]

# A callable is rendered per attempt, so under fallback the model that serves the turn gets
# its own prompt (app/agent/prompts.py).
SystemPrompt = Union[str, "Callable[[ModelHandle], str]"]


@dataclass(frozen=True)
class ModelHandle:
    model_id: str
    region: str
    role: ModelRole
    provider: Provider = "bedrock"

    def __str__(self) -> str:
        return f"{self.model_id}@{self.region}"


class NoModelAvailable(RuntimeError):
    """Every configured model refused the request."""


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


def configured_model_handle(settings: Settings, role: ModelRole) -> ModelHandle | None:
    """Resolve an approved UI model role without accepting an arbitrary model id."""
    if role == "primary" and settings.bedrock_primary_model_id:
        return ModelHandle(settings.bedrock_primary_model_id, settings.bedrock_region, role)
    if role == "secondary" and settings.bedrock_secondary_model_id:
        return ModelHandle(settings.bedrock_secondary_model_id, settings.secondary_region, role)
    if role == "apertus" and settings.apertus_base_url and settings.apertus_model_id:
        return ModelHandle(
            settings.apertus_model_id, settings.apertus_region, role, provider="openai"
        )
    return None


def resolve_system(system: SystemPrompt, handle: ModelHandle) -> str:
    return system(handle) if callable(system) else system


def error_code(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if isinstance(response, dict):
        code = response.get("Error", {}).get("Code")
        if isinstance(code, str):
            return code
    return type(exc).__name__


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
