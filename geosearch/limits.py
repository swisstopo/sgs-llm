"""Hard bounds and completeness metadata for feature retrieval.

Feature count is the product limit the user sees, but a single polygon can be larger
than thousands of points. Coordinate and byte budgets keep the 4 GB Fargate task from
turning an apparently modest feature count into an out-of-memory restart.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

MAX_FEATURES = 100_000
MAX_COORDINATES = 10_000_000
MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024


@dataclass(frozen=True)
class FetchResult:
    features: list[dict[str, Any]]
    complete: bool = True
    limit_reason: str | None = None
    capped_cells: int = 0
    failed_cells: int = 0


def _coordinate_count(value: Any) -> int:
    """Number of coordinate positions, not scalar ordinates, in nested GeoJSON."""
    if not isinstance(value, list) or not value:
        return 0
    if isinstance(value[0], (int, float)):
        return 1
    return sum(_coordinate_count(child) for child in value)


@dataclass
class FeatureBudget:
    max_features: int = MAX_FEATURES
    max_coordinates: int = MAX_COORDINATES
    max_bytes: int = MAX_UNCOMPRESSED_BYTES
    feature_count: int = 0
    coordinate_count: int = 0
    byte_count: int = 0
    reason: str | None = None
    _ids: set[Any] = field(default_factory=set, repr=False)

    def add(self, feature: dict[str, Any]) -> bool:
        """Charges one unique feature, returning false without mutating on overflow."""
        feature_id = feature.get("id")
        if feature_id is not None and feature_id in self._ids:
            return True

        coordinates = _coordinate_count(
            (feature.get("geometry") or {}).get("coordinates")
        )
        size = len(
            json.dumps(
                feature, ensure_ascii=False, separators=(",", ":"), default=str
            ).encode("utf-8")
        )
        if self.feature_count + 1 > self.max_features:
            self.reason = "feature_limit"
            return False
        if self.coordinate_count + coordinates > self.max_coordinates:
            self.reason = "coordinate_limit"
            return False
        if self.byte_count + size > self.max_bytes:
            self.reason = "byte_limit"
            return False

        self.feature_count += 1
        self.coordinate_count += coordinates
        self.byte_count += size
        if feature_id is not None:
            self._ids.add(feature_id)
        return True
