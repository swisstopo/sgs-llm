"""Administrative qualifiers and explicit division lookup failures."""

from __future__ import annotations

import re
from typing import Any

_QUALIFIERS = (
    (
        r"(?:stadt|gemeinde|commune(?: de)?|ville(?: de)?|comune(?: di)?|città(?: di)?|city of|municipality of)",
        "gemeinde",
    ),
    (r"(?:kanton|canton(?: de| of)?|cantone(?: di)?)", "kanton"),
    (r"(?:bezirk|district(?: de)?|distretto(?: di)?)", "bezirk"),
)


class DivisionLookupError(ValueError):
    def __init__(
        self, message: str, candidates: list[dict[str, Any]] | None = None
    ) -> None:
        super().__init__(message)
        self.candidates = candidates or []


def division_query(name: str, kind: str | None) -> tuple[str, str | None]:
    name = " ".join(name.split())
    for pattern, inferred in _QUALIFIERS:
        match = re.match(rf"^{pattern}\s+(.+)$", name, re.IGNORECASE)
        if match:
            if kind and kind != inferred:
                raise DivisionLookupError(
                    "The administrative qualifier conflicts with the requested kind."
                )
            return match.group(1), inferred
    return name, kind


def candidate(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row.get(key) for key in ("name", "kind", "canton", "bbox")} | {
        "division_ref": row["s3_key"],
    }
