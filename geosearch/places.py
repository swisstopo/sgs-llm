"""Explicit division lookup failures and candidate metadata."""

from __future__ import annotations

from typing import Any


class DivisionLookupError(ValueError):
    def __init__(
        self, message: str, candidates: list[dict[str, Any]] | None = None
    ) -> None:
        super().__init__(message)
        self.candidates = candidates or []


def candidate(row: dict[str, Any]) -> dict[str, Any]:
    return {key: row.get(key) for key in ("name", "kind", "canton", "bbox")} | {
        "division_ref": row["s3_key"],
    }
