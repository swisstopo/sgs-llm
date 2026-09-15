"""Search vocabulary for opaque official catalogue labels.

These are aliases, not new datasets or changes to source metadata. Applied at read
 time so an existing index also benefits without changing its embedding vectors.
"""

from __future__ import annotations

import re

CATALOG_TERMS: dict[str, tuple[str, ...]] = {
    "ch.swisstopo-vd.amtliche-vermessung": (
        "Parzelle",
        "Parzellen",
        "Grundstück",
        "Grundstücke",
        "amtliche Vermessung",
        "parcelle",
        "parcelles",
        "mensuration officielle",
        "parcel",
        "parcels",
        "cadastral survey",
        "particella",
        "particelle",
        "misurazione ufficiale",
        "EGRID",
    ),
    "ch.kantone.cadastralwebmap-farbe": (
        "Katasterplan",
        "Katasterkarte",
        "plan cadastral",
        "carte cadastrale",
        "cadastral map",
        "mappa catastale",
        "piano catastale",
    ),
}


def alias_matches(query: str, layer_id: str) -> bool:
    words = " " + " ".join(re.findall(r"\w+", query.casefold())) + " "
    return any(
        " " + term.casefold() + " " in words for term in CATALOG_TERMS.get(layer_id, ())
    )
