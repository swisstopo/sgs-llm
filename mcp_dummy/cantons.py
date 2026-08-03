"""Canton name aliases, keyed to the two-letter codes.

Needed because the geo.admin.ch location index does not match every canton name in
every national language: searching `origins=kantone` for "Wallis" returns nothing
(only the French "Valais" matches), and the query then falls through to the gazetteer
and returns unrelated places like "Wallisellen". The two-letter code always matches,
so a German, Italian or Romansh canton name is translated to its code before the
lookup. Verified against the live API on 2026-07-30.
"""

from __future__ import annotations

# code -> every name form we accept for it.
CANTON_NAMES: dict[str, tuple[str, ...]] = {
    "AG": ("Aargau", "Argovie", "Argovia"),
    "AI": (
        "Appenzell Innerrhoden",
        "Appenzell Rhodes-Intérieures",
        "Appenzello Interno",
    ),
    "AR": (
        "Appenzell Ausserrhoden",
        "Appenzell Rhodes-Extérieures",
        "Appenzello Esterno",
    ),
    "BE": ("Bern", "Berne", "Berna"),
    "BL": ("Basel-Landschaft", "Bâle-Campagne", "Basilea Campagna", "Baselland"),
    "BS": ("Basel-Stadt", "Bâle-Ville", "Basilea Città", "Basel"),
    "FR": ("Fribourg", "Freiburg", "Friburgo"),
    "GE": ("Genève", "Genf", "Ginevra", "Geneva"),
    "GL": ("Glarus", "Glaris", "Glarona"),
    "GR": ("Graubünden", "Grisons", "Grigioni", "Grischun", "Grisch un"),
    "JU": ("Jura",),
    "LU": ("Luzern", "Lucerne", "Lucerna"),
    "NE": ("Neuchâtel", "Neuenburg"),
    "NW": ("Nidwalden", "Nidwald", "Nidvaldo"),
    "OW": ("Obwalden", "Obwald", "Obvaldo"),
    "SG": ("St. Gallen", "Sankt Gallen", "Saint-Gall", "San Gallo", "St Gallen"),
    "SH": ("Schaffhausen", "Schaffhouse", "Sciaffusa"),
    "SO": ("Solothurn", "Soleure", "Soletta"),
    "SZ": ("Schwyz", "Schwytz", "Svitto"),
    "TG": ("Thurgau", "Thurgovie", "Turgovia"),
    "TI": ("Ticino", "Tessin"),
    "UR": ("Uri",),
    "VD": ("Vaud", "Waadt"),
    "VS": ("Valais", "Wallis", "Vallese"),
    "ZG": ("Zug", "Zoug", "Zugo"),
    "ZH": ("Zürich", "Zurich", "Zurigo", "Zurigo"),
}

_ALIASES: dict[str, str] = {}
for _code, _names in CANTON_NAMES.items():
    _ALIASES[_code.lower()] = _code
    for _name in _names:
        _ALIASES[_name.lower()] = _code


def canton_code(text: str) -> str | None:
    """The canton code a query names, if it names one at all.

    Matches the whole string first, then any single word in it, so both "Wallis" and
    "Hochwassergefahren im Wallis" resolve.
    """
    cleaned = text.strip().lower()
    if not cleaned:
        return None
    if cleaned in _ALIASES:
        return _ALIASES[cleaned]
    words = [w.strip(".,;:!?()[]\"'") for w in cleaned.split()]
    for word in words:
        # Two-letter codes are only honoured when written in uppercase in the original
        # text; otherwise "in" or "so" would resolve to a canton.
        if len(word) == 2 and word.upper() in CANTON_NAMES and word.upper() in text:
            return word.upper()
    for size in (3, 2, 1):
        for start in range(len(words) - size + 1):
            phrase = " ".join(words[start : start + size])
            if phrase in _ALIASES and len(phrase) > 2:
                return _ALIASES[phrase]
    return None
