"""Build provenance and offline integrity checks for a publishable index bundle."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import duckdb
import faiss

INDEX_FILES = (
    "geosearch.duckdb",
    "layer_title.faiss",
    "layer_description.faiss",
    "division_name.faiss",
)


def write_metadata(directory: Path, layers: int, divisions: int, model: str) -> None:
    data = {
        "built_at": datetime.now(UTC).isoformat(),
        "catalogue_layers": layers,
        "divisions": divisions,
        "model": model,
    }
    (directory / "meta.json").write_text(json.dumps(data, indent=2) + "\n")


def health_metadata(
    directory: Path, counts: dict[str, int], model: str
) -> dict[str, Any]:
    """Legacy bundles have unknown build dates; never substitute startup time."""
    metadata: dict[str, Any] = {
        "built_at": None,
        "catalogue_layers": counts["layers"],
        "divisions": counts["divisions"],
        "model": model,
    }
    path = directory / "meta.json"
    if path.exists():
        saved = json.loads(path.read_text())
        if any(
            saved.get(key) != metadata[key]
            for key in ("catalogue_layers", "divisions", "model")
        ):
            raise ValueError("meta.json does not describe the loaded index")
        date = datetime.fromisoformat(saved["built_at"])
        if date.tzinfo is None:
            raise ValueError("meta.json built_at must include a timezone")
        metadata["built_at"] = saved["built_at"]
    return metadata


def records(directory: Path, table: str) -> list[dict[str, Any]]:
    if table not in ("layers", "divisions"):
        raise ValueError("Unknown index table")
    with duckdb.connect(str(directory / "geosearch.duckdb"), read_only=True) as db:
        cursor = db.execute(f"SELECT * EXCLUDE (rid) FROM {table} ORDER BY rid")
        names = [column[0] for column in cursor.description]
        return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def validate_bundle(
    directory: Path, *, require_metadata: bool = True
) -> dict[str, Any]:
    required = (*INDEX_FILES, "meta.json") if require_metadata else INDEX_FILES
    for name in required:
        if not (directory / name).is_file() or not (directory / name).stat().st_size:
            raise ValueError(f"Missing or empty index file: {name}")
    layers, divisions = records(directory, "layers"), records(directory, "divisions")
    if not layers or not divisions:
        raise ValueError(
            "A publishable index needs catalogue layers and division boundaries"
        )
    if len({row["layer_id"] for row in layers}) != len(layers):
        raise ValueError("Duplicate catalogue layer ids")
    dimensions = set()
    for name, count in (
        ("layer_title", len(layers)),
        ("layer_description", len(layers)),
        ("division_name", len(divisions)),
    ):
        index = faiss.read_index(str(directory / f"{name}.faiss"))
        if index.ntotal != count:
            raise ValueError(f"{name}.faiss count does not match the database")
        dimensions.add(index.d)
    if len(dimensions) != 1:
        raise ValueError("Index vector dimensions differ")
    for row in divisions:
        key = Path(row["s3_key"])
        if key.is_absolute() or ".." in key.parts:
            raise ValueError("Invalid division boundary path")
        path = directory / "s3" / key
        data = json.loads(path.read_text())
        features = data.get("features", [])
        if not features or len(features) != row["feature_count"]:
            raise ValueError(f"Missing/incomplete boundary features: {key}")
        if any(not feature.get("geometry") for feature in features):
            raise ValueError(f"Missing boundary geometry: {key}")
    with duckdb.connect(str(directory / "geosearch.duckdb"), read_only=True) as db:
        model = db.execute("SELECT value FROM meta WHERE key='model'").fetchone()
    if not model:
        raise ValueError("Index has no embedding model")
    return health_metadata(
        directory, {"layers": len(layers), "divisions": len(divisions)}, model[0]
    )
