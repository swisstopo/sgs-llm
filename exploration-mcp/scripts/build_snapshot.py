"""Rebuild portable JSON snapshots from the SGS index and multilingual catalogue.

Run from this project directory after the source data has been refreshed:

    python scripts/build_snapshot.py \
      --database ../index/geosearch.duckdb \
      --catalog /path/to/swisstopo_catalog/described_catalog.json
"""

from __future__ import annotations

import argparse
import json
from datetime import date
from pathlib import Path
from typing import Any

import duckdb


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Build the portable MCP search snapshots.")
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("src/swisstopo_mcp/data"),
    )
    parser.add_argument("--date", default=date.today().isoformat())
    return parser


def _clean_translations(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {
        str(language): str(text).strip()
        for language, text in value.items()
        if isinstance(text, str) and text.strip()
    }


def build(database: Path, described_catalog: Path, output: Path, generated_at: str) -> None:
    described_rows = json.loads(described_catalog.read_text(encoding="utf-8"))
    described = {
        row["dataset_name"]: row
        for row in described_rows
        if isinstance(row, dict) and isinstance(row.get("dataset_name"), str)
    }
    connection = duckdb.connect(str(database), read_only=True)
    layer_rows = connection.execute(
        "SELECT layer_id, title, description, layer_type, topics, attribution, "
        "data_owner, details_url, queryable, displayable FROM layers ORDER BY rid"
    ).fetchall()
    division_rows = connection.execute(
        "SELECT rid, name, kind, canton, bbox, layer_id, feature_count FROM divisions ORDER BY rid"
    ).fetchall()

    datasets = []
    for (
        dataset_id,
        title,
        description,
        layer_type,
        topics,
        attribution,
        data_owner,
        details_url,
        queryable,
        displayable,
    ) in layer_rows:
        enriched = described.get(dataset_id, {})
        titles = _clean_translations(enriched.get("title"))
        descriptions = _clean_translations(enriched.get("description"))
        summaries = _clean_translations(enriched.get("ai_summary"))
        titles.setdefault("de", str(title or dataset_id))
        if description:
            descriptions.setdefault("de", str(description))
        datasets.append(
            {
                "dataset_id": dataset_id,
                "titles": titles,
                "descriptions": descriptions,
                "summaries": summaries,
                "layer_type": layer_type,
                "topics": [value for value in str(topics or "").split(",") if value],
                "attribution": attribution,
                "data_owner": data_owner,
                "details_url": details_url,
                "queryable": bool(queryable),
                "displayable": bool(displayable),
            }
        )

    divisions = [
        {
            "division_ref": f"division:{rid}",
            "name": name,
            "kind": kind,
            "canton": canton,
            "bbox": list(bbox) if bbox is not None else None,
            "source_layer_id": layer_id,
            "feature_count": feature_count,
        }
        for rid, name, kind, canton, bbox, layer_id, feature_count in division_rows
    ]

    output.mkdir(parents=True, exist_ok=True)
    dataset_payload: dict[str, Any] = {
        "metadata": {
            "generated_at": generated_at,
            "dataset_count": len(datasets),
            "sources": [
                str(database),
                str(described_catalog),
                "https://api3.geo.admin.ch",
            ],
            "languages": ["de", "fr", "en"],
        },
        "datasets": datasets,
    }
    division_payload: dict[str, Any] = {
        "metadata": {
            "generated_at": generated_at,
            "division_count": len(divisions),
            "bbox_crs": "EPSG:4326",
            "sources": [
                "swissBOUNDARIES3D",
                "Amtliches Ortschaftenverzeichnis",
                str(database),
            ],
        },
        "divisions": divisions,
    }
    (output / "datasets.json").write_text(
        json.dumps(dataset_payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    (output / "divisions.json").write_text(
        json.dumps(division_payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"wrote {len(datasets)} datasets and {len(divisions)} divisions to {output}")


if __name__ == "__main__":
    arguments = _parser().parse_args()
    build(
        arguments.database,
        arguments.catalog,
        arguments.output,
        arguments.date,
    )
