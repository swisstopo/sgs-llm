"""Read-only access to administrative boundaries shipped in the geosearch image."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class BoundaryStore:
    """Load pre-built division GeoJSON from a contained image directory."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory).resolve()

    def get_geojson(self, key: str) -> dict[str, Any]:
        path = (self.directory / key).resolve()
        if not path.is_relative_to(self.directory):
            raise ValueError(f"boundary key escapes {self.directory}: {key!r}")
        parsed: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return parsed

    def count(self) -> int:
        return sum(1 for _ in self.directory.rglob("*.geojson"))
