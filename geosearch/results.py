"""Server-side cache of fetched feature sets.

Tools exchange short handles (`result_id`) rather than whole FeatureCollections. A
few hundred Swiss features are far larger than a 14B model's usable context, and
round-tripping them through the model would be both expensive and lossy - so the
features stay here and only summaries cross the wire. A real geodata MCP server would
do the same.
"""

from __future__ import annotations

import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

MAX_RESULTS = 64


@dataclass
class FeatureSet:
    result_id: str
    layer_id: str
    title: str
    features: list[dict[str, Any]] = field(default_factory=list)
    bbox: list[float] | None = None
    complete: bool = True
    limit_reason: str | None = None


class ResultCache:
    def __init__(self, limit: int = MAX_RESULTS) -> None:
        self._limit = limit
        self._items: OrderedDict[str, FeatureSet] = OrderedDict()

    def put(
        self,
        layer_id: str,
        title: str,
        features: list[dict[str, Any]],
        *,
        complete: bool = True,
        limit_reason: str | None = None,
    ) -> FeatureSet:
        result_id = f"fs_{uuid.uuid4().hex[:12]}"
        entry = FeatureSet(
            result_id=result_id,
            layer_id=layer_id,
            title=title,
            features=features,
            complete=complete,
            limit_reason=limit_reason,
        )
        self._items[result_id] = entry
        self._items.move_to_end(result_id)
        while len(self._items) > self._limit:
            self._items.popitem(last=False)
        return entry

    def get(self, result_id: str) -> FeatureSet | None:
        entry = self._items.get(result_id)
        if entry is not None:
            self._items.move_to_end(result_id)
        return entry
