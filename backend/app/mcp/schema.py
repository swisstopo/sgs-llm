"""Converting MCP tool declarations into Bedrock tool specifications.

The MCP server owns the tool catalogue and we do not control its JSON Schema, so the
conversion is defensive: normalise what Bedrock requires, drop what it does not
understand, and never fail a whole turn because one tool has an odd schema.
"""

from __future__ import annotations

from typing import Any

# Pydantic-generated schemas carry presentation keys Bedrock has no use for, and Mistral
# is less tolerant of unexpected schema keys than Claude.
_DROPPED_KEYS = frozenset({"title", "$schema", "definitions", "additionalProperties"})

MAX_DESCRIPTION_CHARS = 900


def _clean(node: Any) -> Any:
    if isinstance(node, dict):
        return {k: _clean(v) for k, v in node.items() if k not in _DROPPED_KEYS}
    if isinstance(node, list):
        return [_clean(v) for v in node]
    return node


def normalise_input_schema(schema: Any) -> dict[str, Any]:
    """Coerces a tool's input schema into the object shape Bedrock expects."""
    cleaned = _clean(schema) if isinstance(schema, dict) else {}
    if cleaned.get("type") != "object":
        cleaned["type"] = "object"
    if not isinstance(cleaned.get("properties"), dict):
        cleaned["properties"] = {}
    required = cleaned.get("required")
    if not isinstance(required, list):
        cleaned.pop("required", None)
    return cleaned


def to_tool_spec(name: str, description: str | None, input_schema: Any) -> dict[str, Any]:
    """One entry of Bedrock's `toolConfig.tools`."""
    return {
        "toolSpec": {
            "name": name,
            "description": (description or name)[:MAX_DESCRIPTION_CHARS],
            "inputSchema": {"json": normalise_input_schema(input_schema)},
        }
    }
