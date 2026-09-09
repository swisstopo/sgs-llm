"""Repairing the argument shapes models emit, against the tool's own schema.

Three repairs, each for a failure seen in swisstopo's 2026-09-08 test round rather than
imagined: a place passed as the `{name, kind}` object search_locations returned, every
optional property filled in with null, and a scalar/array confusion. Untouched, each one
is a pydantic validation error the weaker models do not recover from - Apertus repeated
the identical call instead.

Nothing here guesses at intent. A repair applies only where the schema says what the
parameter must be, and only where exactly one reading is possible: two layer ids stay two
layer ids, because choosing one would be choosing which dataset the user asked about.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# The nested key holding the value when a model passes an object where a name was wanted.
# `name` is what search_locations returns; the others appear in neighbouring tool output.
_NAME_KEYS = ("name", "label", "title", "value")
_KIND_KEYS = ("kind", "type", "level")


def normalise_arguments(arguments: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """`arguments` repaired where `schema` says unambiguously what was meant."""
    properties = schema.get("properties")
    if not isinstance(properties, dict):
        return arguments
    required = set(schema.get("required") or [])

    result: dict[str, Any] = {}
    for key, value in arguments.items():
        declared = properties.get(key)
        if not isinstance(declared, dict):
            result[key] = value
            continue

        wanted = declared.get("type")

        if value is None and key not in required:
            logger.info("dropping null optional argument %r", key)
            continue

        if wanted == "string" and isinstance(value, dict):
            name = next((value[k] for k in _NAME_KEYS if isinstance(value.get(k), str)), None)
            if name is not None:
                result[key] = name
                sibling = f"{key}_kind"
                if sibling in properties and sibling not in arguments:
                    kind = next(
                        (value[k] for k in _KIND_KEYS if isinstance(value.get(k), str)), None
                    )
                    if kind is not None:
                        result[sibling] = kind
                logger.info("flattened object argument %r", key)
                continue

        if wanted == "string" and isinstance(value, list) and len(value) == 1:
            result[key] = value[0]
            continue

        if wanted == "array" and not isinstance(value, list):
            result[key] = [value]
            continue

        result[key] = value

    return result
