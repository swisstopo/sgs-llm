"""Generate and validate a reproducible large GeoParquet layer.

Run inside the geosearch image so the exact deployed PyArrow version is exercised::

    python -m geosearch.large_layer_smoke --features 100000 --output-dir /output
"""

from __future__ import annotations

import argparse
import json
import math
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pyarrow.parquet as pq  # type: ignore[import-untyped]

from .artifacts import ROW_GROUP_SIZE, write_source


def synthetic_line_features(count: int) -> list[dict[str, Any]]:
    """Deterministic short road-like segments spread across the Valais bbox."""
    if count < 1:
        raise ValueError("feature count must be positive")
    columns = math.ceil(math.sqrt(count))
    rows = math.ceil(count / columns)
    lon_step = 1.65 / max(1, columns - 1)
    lat_step = 0.72 / max(1, rows - 1)
    features: list[dict[str, Any]] = []
    for index in range(count):
        column = index % columns
        row = index // columns
        lon = 6.75 + column * lon_step
        lat = 45.85 + row * lat_step
        lon_delta = min(lon_step * 0.45, 0.005)
        lat_delta = min(lat_step * 0.2, 0.002)
        if columns > 1 and column == columns - 1:
            lon_delta *= -1
        if rows > 1 and row == rows - 1:
            lat_delta *= -1
        features.append(
            {
                "type": "Feature",
                "id": index,
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[lon, lat], [lon + lon_delta, lat + lat_delta]],
                },
                "properties": {
                    "name": f"Synthetic road {index}",
                    "road_class": ("main", "regional", "local")[index % 3],
                    "sequence": index,
                },
            }
        )
    return features


def build_smoke_layer(count: int, output_dir: Path) -> dict[str, Any]:
    features = synthetic_line_features(count)
    output_dir.mkdir(parents=True, exist_ok=True)
    parquet = output_dir / "large.parquet"
    artifact = write_source(
        features,
        parquet,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
        complete=True,
    )
    manifest = output_dir / "manifest.json"
    manifest.write_bytes(artifact.manifest.to_json())

    parquet_file = pq.ParquetFile(parquet)
    if parquet_file.metadata.num_rows != count:
        raise RuntimeError(
            f"GeoParquet row count is {parquet_file.metadata.num_rows}, expected {count}"
        )
    row_sizes = [
        parquet_file.metadata.row_group(index).num_rows
        for index in range(parquet_file.num_row_groups)
    ]
    # GDAL's sorted Parquet writer treats ROW_GROUP_SIZE as an upper bound, so
    # groups can close a few rows early. The pruning contract is the bound, not
    # an exact group count.
    assert row_sizes
    assert max(row_sizes) <= ROW_GROUP_SIZE
    assert parquet_file.num_row_groups >= math.ceil(count / ROW_GROUP_SIZE)
    return {
        "features": count,
        "parquet_rows": parquet_file.metadata.num_rows,
        "parquet_bytes": artifact.byte_count,
        "row_groups": parquet_file.num_row_groups,
        "source_sha256": artifact.checksum,
        "manifest": str(manifest),
        "min_zoom": artifact.manifest.min_zoom,
        "max_zoom": artifact.manifest.max_zoom,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a large local layer fixture.")
    parser.add_argument("--features", type=int, default=100_000)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build_smoke_layer(args.features, args.output_dir), sort_keys=True))


if __name__ == "__main__":
    main()
