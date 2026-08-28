"""Chooses which model serves a turn, and invokes it through its provider.

Model *selection* lives here; model *access* lives in the provider modules. The split
exists because the pilot now reaches two unrelated kinds of endpoint - Bedrock's Converse
API and a self-hosted OpenAI-compatible one - and only the selection rules are shared.
"""

from __future__ import annotations

import logging
from typing import Any

from ..config import Settings
from .apertus import ApertusOffline, ApertusProvider
from .bedrock import BedrockProvider
from .models import (
    ConverseResult,
    ModelHandle,
    ModelRole,
    NoModelAvailable,
    SystemPrompt,
    configured_model_handle,
    error_code,
)

logger = logging.getLogger(__name__)

# ValidationException is excluded: it means our request was malformed, not that the model
# is unavailable, and it would otherwise disable the primary for the whole process.
_UNAVAILABLE_ERRORS = frozenset({"AccessDeniedException", "ResourceNotFoundException"})

DEFAULT_MAX_TOKENS = 2048


class ModelRouter:
    """Resolves and invokes the configured models, newest-preferred first."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._bedrock = BedrockProvider()
        self._apertus = ApertusProvider(settings)
        self._unavailable: set[str] = set()

    @property
    def handles(self) -> tuple[ModelHandle, ...]:
        """Every configured model, in preference order, skipping unset ids."""
        candidates = (
            configured_model_handle(self._settings, "primary"),
            configured_model_handle(self._settings, "secondary"),
            configured_model_handle(self._settings, "apertus"),
        )
        return tuple(handle for handle in candidates if handle is not None)

    @property
    def usable_handles(self) -> tuple[ModelHandle, ...]:
        return tuple(h for h in self.handles if h.model_id not in self._unavailable)

    @property
    def fallback_candidates(self) -> tuple[ModelHandle, ...]:
        """What an unpinned turn may be served by.

        Apertus is excluded on purpose: it is explicit-only. Answering a Claude request
        with a self-hosted Swiss model would change both the model and the residency
        story without the caller asking for either.
        """
        return tuple(h for h in self.usable_handles if h.provider == "bedrock")

    def handle_for_role(self, role: ModelRole) -> ModelHandle | None:
        """The configured, currently usable model for an explicit UI selection."""
        return next((handle for handle in self.usable_handles if handle.role == role), None)

    async def converse(
        self,
        handle: ModelHandle,
        *,
        messages: list[dict[str, Any]],
        system: SystemPrompt,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
    ) -> ConverseResult:
        """One turn against one model, through whichever provider serves it.

        `max_tokens` unset takes the provider's own default, because Apertus reserves the
        completion against a 28k window while Bedrock has 200k to spend.
        """
        if handle.provider == "openai":
            return await self._apertus.converse(
                handle,
                messages=messages,
                system=system,
                tools=tools,
                max_tokens=(
                    max_tokens if max_tokens is not None else self._settings.apertus_max_tokens
                ),
            )
        return await self._bedrock.converse(
            handle,
            messages=messages,
            system=system,
            tools=tools,
            max_tokens=max_tokens if max_tokens is not None else DEFAULT_MAX_TOKENS,
        )

    async def converse_with_fallback(
        self,
        *,
        messages: list[dict[str, Any]],
        system: SystemPrompt,
        tools: list[dict[str, Any]] | None = None,
        max_tokens: int | None = None,
        pinned: ModelHandle | None = None,
    ) -> ConverseResult:
        """Tries each usable model in order until one answers.

        `pinned` keeps a multi-step turn on the model that started it - switching
        models mid-tool-loop would hand one model's tool_use blocks to another.
        """
        candidates = (pinned,) if pinned is not None else self.fallback_candidates
        if not candidates:
            raise NoModelAvailable("no model is configured")

        last_error: Exception | None = None
        for handle in candidates:
            if handle is None:
                continue
            try:
                return await self.converse(
                    handle, messages=messages, system=system, tools=tools, max_tokens=max_tokens
                )
            except ApertusOffline:
                # Not a fallback condition: an explicit Apertus selection is answered by
                # Apertus or reported as offline. Never cached as unavailable either -
                # the endpoint returns on schedule at 06:30.
                raise
            except Exception as exc:
                code = error_code(exc)
                last_error = exc
                if code in _UNAVAILABLE_ERRORS:
                    if handle.model_id not in self._unavailable:
                        self._unavailable.add(handle.model_id)
                        logger.warning(
                            "model %s unavailable (%s); falling back (docs/llm.md)",
                            handle,
                            code,
                        )
                    continue
                logger.warning("model %s failed with %s", handle, code)
                continue

        raise NoModelAvailable("every configured model refused the request") from last_error
