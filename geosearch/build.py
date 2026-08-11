"""Pre-embeds the swisstopo catalogue and the administrative divisions.

    python -m geosearch.build              # full build
    python -m geosearch.build --no-divisions   # catalogue only, ~30s

Run once; the server only reads what this writes. Everything slow - fetching 896 layer
descriptions, downloading 2000-odd commune polygons, embedding all of it through Bedrock -
happens here so that a search at runtime is one query embedding and two FAISS lookups.

Needs AWS credentials, because embedding is now a Bedrock call (geosearch/index.py).

Output:
    index/geosearch.duckdb      records + the model the vectors came from
    index/*.faiss               title, description and division-name indexes
    index/s3/layers/divisions/  read-only division GeoJSON shipped in the image
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

from .geometry import bounding_box
from .index import DEFAULT_MODEL, INDEX_DIR, Embedder, build
from .swisstopo import DIVISIONS, Swisstopo, feature_name

logger = logging.getLogger(__name__)

# Historical directory name retained so existing indexes remain compatible. These
# boundaries now ship in the image and are never copied to the generated-layer bucket.
S3_MIRROR = "s3"

# Given every feature of one division, the abbreviation of the canton it lies in.
CantonLocator = Callable[[list[dict[str, Any]]], "str | None"]


async def collect(
    api: Swisstopo, lang: str, with_divisions: bool, mirror: Path
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    logger.info("fetching catalogue (%s)", lang)
    layers = await api.catalog(lang)
    logger.info("catalogue: %d layers, %d queryable", len(layers), sum(x["queryable"] for x in layers))

    divisions: list[dict[str, Any]] = []
    if not with_divisions:
        return layers, divisions

    keys: dict[str, str] = {}
    locate_canton: CantonLocator = lambda group: None  # noqa: E731 - until the cantons land

    # DIVISIONS runs coarsest first, so the cantons are in hand before the levels that
    # need them to fill in a canton of their own.
    for spec in DIVISIONS:
        logger.info("downloading %s boundaries", spec.kind)
        groups = await api.fetch_divisions(spec, lang)
        logger.info("%s: %d divisions, %d features", spec.kind, len(groups), sum(map(len, groups)))
        if spec.kind == "kanton":
            locate_canton = _canton_locator(groups)

        for group in groups:
            props = group[0].get("properties") or {}
            name = feature_name(props)
            # The commune layer also holds the big lakes and Staatswald Galm, which belong
            # to no commune. They are worth resolving as locations - "Messstationen im
            # Zürichsee" is a fair question - but calling them communes would be a lie.
            kind = _kind(props.get("objektart_lookup"), spec.kind)
            key = _s3_key(keys, kind, name)
            collection = {"type": "FeatureCollection", "features": group}

            path = mirror / key
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(collection, ensure_ascii=False), encoding="utf-8")

            divisions.append(
                {
                    "name": name,
                    "kind": kind,
                    # Communes carry their canton and cantons are their own; districts and
                    # localities carry none, so theirs is looked up from the geometry.
                    "canton": props.get("kanton") or props.get("ak") or locate_canton(group),
                    "bbox": bounding_box(group),
                    "layer_id": spec.layer_id,
                    "s3_key": key,
                    "feature_count": len(group),
                }
            )
    return layers, divisions


def _s3_key(taken: dict[str, str], kind: str, name: str | None) -> str:
    """A key for one division, unique even when two names slug the same.

    `_slug` is lossy - 'Bévilard' and 'Bevilard' both become 'bevilard' - and the loser of
    a collision would have its polygon overwritten by the winner while still pointing at
    the key, so the map would show the wrong place under the right name.
    """
    key = f"layers/divisions/{kind}/{_slug(name)}.geojson"
    if taken.setdefault(key, name or "") != name:
        logger.warning("%s: slug collision on %r, suffixing", kind, name)
        key = key.replace(".geojson", f"-{len(taken)}.geojson")
        taken[key] = name or ""
    return key


def _canton_locator(canton_groups: list[list[dict[str, Any]]]) -> CantonLocator:
    """Point-in-polygon lookup of the canton a division sits in.

    Districts and localities carry no canton of their own - the district layer's only
    properties are `name`, `label` and `flaeche` - so without this two thirds of the rows
    would come back with `canton: null`, which is the field an agent uses to tell one
    Bonstetten from another.
    """
    from shapely.geometry import shape
    from shapely.strtree import STRtree

    polygons, codes = [], []
    for group in canton_groups:
        code = (group[0].get("properties") or {}).get("ak")
        for feature in group:
            geometry = feature.get("geometry")
            if code and isinstance(geometry, dict):
                polygons.append(shape(geometry))
                codes.append(code)
    tree = STRtree(polygons)

    def locate(group: list[dict[str, Any]]) -> str | None:
        for feature in group:
            geometry = feature.get("geometry")
            if not isinstance(geometry, dict):
                continue
            # A representative point is guaranteed to be *inside* its polygon; a centroid
            # is not, and Swiss communes are concave enough for that to matter.
            hits = tree.query(shape(geometry).representative_point(), predicate="intersects")
            if len(hits):
                return str(codes[int(hits[0])])
        return None

    return locate


def _kind(objektart: str | None, default: str) -> str:
    """What kind of thing a boundary feature actually is.

    swissBOUNDARIES3D tags commune-layer rows with an `objektart_lookup`; everything
    that is not `gemeindegebiet` is a lake, a shared territory (`kommunanz`) or
    Staatswald Galm. Canton and district rows carry no such tag at all.
    """
    if objektart is None or objektart == "gemeindegebiet":
        return default
    return objektart


def _slug(name: str | None) -> str:
    """Filesystem- and S3-safe key fragment.

    Swiss place names carry umlauts, accents and slashes ('Biel/Bienne'), none of which
    belong in a key. German umlauts transliterate to digraphs (ü -> ue) because that is
    how the names are conventionally written without them; everything else has its
    diacritics decomposed and dropped by unicodedata, which beats a hand-written
    substitution list - that list silently passed 'â' straight through.
    """
    text = (name or "unnamed").lower()
    for src, dst in (("ä", "ae"), ("ö", "oe"), ("ü", "ue")):
        text = text.replace(src, dst)
    stripped = unicodedata.normalize("NFKD", text)
    ascii_only = "".join(c for c in stripped if not unicodedata.combining(c))
    return "".join(c if c.isalnum() and c.isascii() else "-" for c in ascii_only).strip("-") or "unnamed"


async def main_async(args: argparse.Namespace) -> None:
    directory = Path(args.out)
    mirror = directory / S3_MIRROR

    async with Swisstopo() as api:
        layers, divisions = await collect(api, args.lang, not args.no_divisions, mirror)

    if not layers:
        raise SystemExit("catalogue came back empty - refusing to write an index over it")

    logger.info("embedding with %s", args.model)
    embedder = Embedder(args.model)
    stats = build(directory, layers, divisions, embedder, args.reuse_layer_vectors)
    logger.info("built %s: %s", directory, stats)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=str(INDEX_DIR))
    parser.add_argument("--lang", default="de")
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--no-divisions", action="store_true", help="skip the boundary download")
    parser.add_argument(
        "--reuse-layer-vectors",
        action="store_true",
        help="keep the existing layer indexes instead of re-embedding 896 titles and "
        "abstracts (~100 s of Bedrock calls; it used to be 20 minutes of CPU, which is "
        "why the flag exists). Only the divisions are rebuilt. Refuses if the stored "
        "vectors no longer match the catalogue.",
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
