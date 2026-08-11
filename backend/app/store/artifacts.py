"""Memory-only legacy GeoJSON artifacts for the dummy server and eval harness."""

from __future__ import annotations

import json
from collections import OrderedDict

from ..config import Settings

# Bounded so a long-running test or eval task cannot grow without limit.
_LOCAL_MAX_ENTRIES = 64


class ArtifactStore:
    def __init__(self, settings: Settings) -> None:
        del settings  # Retain the constructor contract used by the harness.
        self._local: OrderedDict[str, bytes] = OrderedDict()

    async def publish_geojson(self, name: str, feature_collection: dict[str, object]) -> str | None:
        """Store one FeatureCollection and return its relative legacy data path."""
        body = json.dumps(feature_collection, ensure_ascii=False).encode("utf-8")
        self._local[name] = body
        self._local.move_to_end(name)
        while len(self._local) > _LOCAL_MAX_ENTRIES:
            self._local.popitem(last=False)
        return f"/data/{name}"

    def read_local(self, name: str) -> bytes | None:
        return self._local.get(name)
