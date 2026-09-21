"""Build a guarded candidate, without publishing or modifying the downloaded index."""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
from pathlib import Path
from typing import Any

from .build import collect
from .index import DEFAULT_MODEL, Embedder, build
from .index_metadata import records, validate_bundle
from .swisstopo import Swisstopo


def catalogue_key(rows: list[dict[str, Any]]) -> str:
    return json.dumps(sorted(rows, key=lambda row: row["layer_id"]), sort_keys=True)


def check_count(old: int, new: int) -> None:
    if old <= 0 or new <= 0 or new * 100 < old * 95:
        raise ValueError(
            f"Catalogue count {old} -> {new}: empty or dropped by more than 5%"
        )


async def refresh(published: Path, output: Path, *, force: bool = False) -> bool:
    previous = validate_bundle(published, require_metadata=False)
    if output.exists():
        raise ValueError("Candidate directory must not exist; use a fresh output path")
    old_layers = records(published, "layers")
    async with Swisstopo() as api:
        layers = await api.catalog("de")
        check_count(len(old_layers), len(layers))
        # Ignore remote ordering, but include every stored metadata field. Vector reuse
        # requires the old rid order, which we explicitly keep when the catalogue matches.
        fields = old_layers[0].keys()
        normalized = [{key: row[key] for key in fields} for row in layers]
        unchanged = catalogue_key(old_layers) == catalogue_key(normalized)
        if unchanged and not force:
            print("Catalogue unchanged; no build, publication or deployment")
            return False
        if unchanged:
            layers = old_layers
        output.mkdir(parents=True)
        _, divisions = await collect(api, "de", True, output / "s3", layers=layers)
    # Also reject a truncated boundary catalogue before any vector generation.
    check_count(previous["divisions"], len(divisions))
    reuse = unchanged and previous["model"] == DEFAULT_MODEL
    if reuse:
        for name in ("layer_title.faiss", "layer_description.faiss"):
            shutil.copyfile(published / name, output / name)
    build(output, layers, divisions, Embedder(DEFAULT_MODEL), reuse_layer_vectors=reuse)
    validate_bundle(output)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--published", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--force", action="store_true", help="Rebuild even an unchanged catalogue"
    )
    args = parser.parse_args()
    asyncio.run(refresh(args.published, args.out, force=args.force))


if __name__ == "__main__":
    main()
