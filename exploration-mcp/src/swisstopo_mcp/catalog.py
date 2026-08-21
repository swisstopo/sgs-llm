"""Portable catalogue and division search over packaged JSON snapshots."""

from __future__ import annotations

import json
import math
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from .guides import VALID_DIVISION_KINDS, VALID_LANGUAGES

DATA_DIR = Path(__file__).with_name("data")
DEFAULT_DATASETS = DATA_DIR / "datasets.json"
DEFAULT_DIVISIONS = DATA_DIR / "divisions.json"

_WORD = re.compile(r"[a-z0-9]+", re.IGNORECASE)

# Function words across the five supported response languages. They are removed only
# from retrieval; titles and descriptions are returned exactly as published.
_STOP_WORDS = {
    "a",
    "about",
    "am",
    "an",
    "and",
    "are",
    "at",
    "au",
    "auf",
    "aus",
    "aux",
    "avec",
    "bei",
    "by",
    "con",
    "cun",
    "da",
    "dal",
    "dalla",
    "dals",
    "dans",
    "das",
    "de",
    "dei",
    "del",
    "della",
    "dellas",
    "dem",
    "den",
    "der",
    "des",
    "die",
    "dil",
    "dils",
    "du",
    "e",
    "ein",
    "eine",
    "einer",
    "en",
    "et",
    "for",
    "from",
    "für",
    "gli",
    "il",
    "im",
    "in",
    "is",
    "ist",
    "la",
    "le",
    "les",
    "mit",
    "nel",
    "o",
    "oder",
    "of",
    "on",
    "or",
    "ou",
    "par",
    "per",
    "pour",
    "sin",
    "su",
    "sur",
    "the",
    "to",
    "un",
    "una",
    "und",
    "une",
    "von",
    "with",
    "zu",
}

# Small concept bridges cover high-value catalogue vocabulary without introducing an LLM
# dependency. Each set is symmetric and multilingual; normal descriptions do the rest.
_SYNONYM_GROUPS = (
    {"avalanche", "avalanches", "lawine", "lawinen", "lavanche", "valanga", "lavina"},
    {"flood", "flooding", "floods", "hochwasser", "crue", "crues", "piena", "inundaziun"},
    {"forest", "forests", "wald", "waelder", "foret", "forets", "bosco", "guaud"},
    {
        "municipality",
        "municipalities",
        "commune",
        "communes",
        "gemeinde",
        "gemeinden",
        "comune",
        "vischnanca",
    },
    {"solar", "sonnenenergie", "solaire", "solare"},
    {"noise", "laerm", "bruit", "rumore"},
    {"address", "addresses", "adresse", "adressen", "indirizzo", "adressa"},
)

_SYNONYMS: dict[str, set[str]] = {}
for _group in _SYNONYM_GROUPS:
    normalized_group = {
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode() for value in _group
    }
    for _value in normalized_group:
        _SYNONYMS[_value] = normalized_group - {_value}

CANTON_NAMES: dict[str, tuple[str, ...]] = {
    "AG": ("Aargau", "Argovie", "Argovia"),
    "AI": ("Appenzell Innerrhoden", "Appenzell Rhodes-Interieures", "Appenzello Interno"),
    "AR": ("Appenzell Ausserrhoden", "Appenzell Rhodes-Exterieures", "Appenzello Esterno"),
    "BE": ("Bern", "Berne", "Berna"),
    "BL": ("Basel-Landschaft", "Bale-Campagne", "Basilea Campagna", "Baselland"),
    "BS": ("Basel-Stadt", "Bale-Ville", "Basilea Citta", "Basel"),
    "FR": ("Fribourg", "Freiburg", "Friburgo"),
    "GE": ("Geneve", "Genf", "Ginevra", "Geneva"),
    "GL": ("Glarus", "Glaris", "Glarona"),
    "GR": ("Graubunden", "Grisons", "Grigioni", "Grischun"),
    "JU": ("Jura",),
    "LU": ("Luzern", "Lucerne", "Lucerna"),
    "NE": ("Neuchatel", "Neuenburg"),
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
    "ZH": ("Zurich", "Zurigo"),
}

_COUNTRY_ALIASES = ("Schweiz", "Suisse", "Svizzera", "Svizra", "Switzerland", "CH")


def normalize(text: object) -> str:
    """Case- and accent-insensitive text suitable for matching identifiers and names."""
    decomposed = unicodedata.normalize("NFKD", str(text or "").casefold())
    ascii_text = "".join(char for char in decomposed if not unicodedata.combining(char))
    return " ".join(_WORD.findall(ascii_text))


def _tokens(text: object) -> list[str]:
    return [token for token in normalize(text).split() if token not in _STOP_WORDS]


def _translated(mapping: object, language: str, fallback: str = "") -> str:
    if not isinstance(mapping, dict):
        return fallback
    for key in (language, "en", "de", "fr"):
        value = mapping.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return fallback


@dataclass(frozen=True)
class _DatasetDocument:
    row: dict[str, Any]
    term_counts: dict[str, float]
    weighted_length: float
    title_norms: tuple[str, ...]
    summary_norms: tuple[str, ...]


class CatalogIndex:
    """Loads and searches the portable snapshots without AWS or a model service."""

    def __init__(
        self,
        datasets_path: Path = DEFAULT_DATASETS,
        divisions_path: Path = DEFAULT_DIVISIONS,
    ) -> None:
        dataset_payload = json.loads(Path(datasets_path).read_text(encoding="utf-8"))
        division_payload = json.loads(Path(divisions_path).read_text(encoding="utf-8"))
        self.dataset_metadata: dict[str, Any] = dataset_payload["metadata"]
        self.division_metadata: dict[str, Any] = division_payload["metadata"]
        self.datasets: list[dict[str, Any]] = dataset_payload["datasets"]
        self.divisions: list[dict[str, Any]] = division_payload["divisions"]
        self._datasets_by_id = {row["dataset_id"]: row for row in self.datasets}
        self._documents = [self._make_document(row) for row in self.datasets]
        self._document_frequency: Counter[str] = Counter()
        for document in self._documents:
            self._document_frequency.update(document.term_counts.keys())
        self._average_length = (
            sum(document.weighted_length for document in self._documents) / len(self._documents)
            if self._documents
            else 1.0
        )
        self._canton_aliases = self._build_canton_aliases()
        self._division_aliases = self._build_division_aliases()

    @property
    def counts(self) -> dict[str, int]:
        return {"datasets": len(self.datasets), "divisions": len(self.divisions)}

    @staticmethod
    def _make_document(row: dict[str, Any]) -> _DatasetDocument:
        counts: dict[str, float] = {}
        titles = tuple(value for value in row.get("titles", {}).values() if value)
        summaries = tuple(value for value in row.get("summaries", {}).values() if value)
        descriptions = tuple(value for value in row.get("descriptions", {}).values() if value)

        def add(values: Iterable[object], weight: float) -> None:
            for value in values:
                for token in _tokens(value):
                    counts[token] = counts.get(token, 0.0) + weight

        add((row["dataset_id"],), 6.0)
        add(titles, 4.0)
        add(summaries, 2.0)
        add(descriptions, 0.45)
        add(row.get("topics", []), 1.5)
        return _DatasetDocument(
            row=row,
            term_counts=counts,
            weighted_length=max(sum(counts.values()), 1.0),
            title_norms=tuple(normalize(value) for value in titles),
            summary_norms=tuple(normalize(value) for value in summaries),
        )

    def get_dataset(self, dataset_id: str, language: str = "en") -> dict[str, Any] | None:
        row = self._datasets_by_id.get(dataset_id.strip())
        if row is None:
            return None
        return self.present_dataset(row, language)

    def present_dataset(self, row: dict[str, Any], language: str) -> dict[str, Any]:
        language = language if language in VALID_LANGUAGES else "en"
        return {
            "dataset_id": row["dataset_id"],
            "title": _translated(row.get("titles"), language, row["dataset_id"]),
            "summary": _translated(row.get("summaries"), language),
            "description": _translated(row.get("descriptions"), language),
            "language": language,
            "queryable": bool(row.get("queryable")),
            "displayable": bool(row.get("displayable")),
            "layer_type": row.get("layer_type"),
            "topics": list(row.get("topics") or []),
            "data_owner": row.get("data_owner"),
            "attribution": row.get("attribution"),
            "details_url": row.get("details_url"),
        }

    def search_datasets(
        self,
        query: str,
        *,
        language: str = "en",
        limit: int = 8,
        queryable_only: bool = False,
    ) -> list[dict[str, Any]]:
        normalized_query = normalize(query)
        query_terms = _tokens(query)
        if not normalized_query or not query_terms:
            return []

        expanded: dict[str, float] = {term: 1.0 for term in query_terms}
        for term in query_terms:
            for synonym in _SYNONYMS.get(term, set()):
                expanded.setdefault(synonym, 0.68)

        scored: list[tuple[float, int, dict[str, Any], list[str], str]] = []
        total = max(len(self._documents), 1)
        for position, document in enumerate(self._documents):
            row = document.row
            if queryable_only and not row.get("queryable"):
                continue
            exact_id = query.strip().casefold() == str(row["dataset_id"]).casefold()
            exact_title = normalized_query in document.title_norms
            title_phrase = any(normalized_query in value for value in document.title_norms)
            summary_phrase = any(normalized_query in value for value in document.summary_norms)
            matched_original = [term for term in query_terms if term in document.term_counts]
            if not exact_id and not exact_title:
                required = 1 if len(query_terms) <= 2 else math.ceil(len(query_terms) / 2)
                if len(set(matched_original)) < required and not title_phrase:
                    continue

            score = 120.0 if exact_id else 0.0
            score += 35.0 if exact_title else 0.0
            score += 16.0 if title_phrase and not exact_title else 0.0
            score += 5.0 if summary_phrase else 0.0
            for term, query_weight in expanded.items():
                frequency = document.term_counts.get(term, 0.0)
                if not frequency:
                    continue
                frequency_saturation = (
                    frequency
                    * 2.2
                    / (
                        frequency
                        + 1.2 * (0.25 + 0.75 * document.weighted_length / self._average_length)
                    )
                )
                document_frequency = self._document_frequency.get(term, 0)
                inverse_frequency = math.log(
                    1 + (total - document_frequency + 0.5) / (document_frequency + 0.5)
                )
                score += query_weight * inverse_frequency * frequency_saturation

            if score <= 0:
                continue
            basis = "exact_id" if exact_id else "exact_title" if exact_title else "catalog_text"
            scored.append((score, position, row, sorted(set(matched_original)), basis))

        scored.sort(key=lambda item: (-item[0], item[1]))
        selected = scored[: max(1, limit)]
        highest = selected[0][0] if selected else 1.0
        results: list[dict[str, Any]] = []
        for score, _, row, matched, basis in selected:
            result = self.present_dataset(row, language)
            result.pop("description", None)
            result["relevance"] = round(score / highest, 4)
            result["match_basis"] = basis
            result["matched_terms"] = matched
            results.append(result)
        return results

    @staticmethod
    def _build_canton_aliases() -> dict[str, str]:
        aliases: dict[str, str] = {}
        for code, names in CANTON_NAMES.items():
            aliases[normalize(code)] = code
            aliases.update({normalize(name): code for name in names})
        return aliases

    def _build_division_aliases(self) -> dict[str, set[int]]:
        aliases: dict[str, set[int]] = {}
        canton_rows = {
            row.get("canton"): index
            for index, row in enumerate(self.divisions)
            if row.get("kind") == "kanton"
        }
        for code, names in CANTON_NAMES.items():
            if (index := canton_rows.get(code)) is None:
                continue
            for value in (code, *names):
                aliases.setdefault(normalize(value), set()).add(index)
        land_index = next(
            (index for index, row in enumerate(self.divisions) if row.get("kind") == "land"),
            None,
        )
        if land_index is not None:
            for value in _COUNTRY_ALIASES:
                aliases.setdefault(normalize(value), set()).add(land_index)
        return aliases

    def canton_code(self, value: str | None) -> str | None:
        if value is None:
            return None
        return self._canton_aliases.get(normalize(value))

    def search_divisions(
        self,
        query: str,
        *,
        kinds: Iterable[str] | None = None,
        canton: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        normalized_query = normalize(query)
        if not normalized_query:
            return []
        wanted_kinds = set(kinds or ())
        if wanted_kinds - set(VALID_DIVISION_KINDS):
            return []
        canton_code = self.canton_code(canton) if canton else None
        if canton and canton_code is None:
            return []

        alias_indexes = self._division_aliases.get(normalized_query, set())
        query_tokens = set(normalized_query.split())
        scored: list[tuple[float, int, str]] = []
        for index, row in enumerate(self.divisions):
            if wanted_kinds and row.get("kind") not in wanted_kinds:
                continue
            if canton_code and row.get("canton") != canton_code:
                continue
            name = normalize(row.get("name"))
            if index in alias_indexes:
                score, basis = 1.0, "alias"
            elif name == normalized_query:
                score, basis = 1.0, "exact_name"
            elif name.startswith(normalized_query) or normalized_query.startswith(name):
                score, basis = 0.9, "prefix"
            elif normalized_query in name:
                score, basis = 0.84, "contains"
            else:
                name_tokens = set(name.split())
                overlap = len(query_tokens & name_tokens) / max(len(query_tokens), 1)
                similarity = SequenceMatcher(None, normalized_query, name).ratio()
                score = max(overlap * 0.82, similarity * 0.78)
                basis = "token" if overlap else "fuzzy"
            if score >= 0.68:
                scored.append((score, index, basis))

        # Snapshot order is hierarchy order, so exact ties return coarser divisions first.
        scored.sort(key=lambda item: (-item[0], item[1]))
        results = []
        for score, index, basis in scored[: max(1, limit)]:
            row = self.divisions[index]
            results.append(
                {
                    "division_ref": row["division_ref"],
                    "name": row["name"],
                    "kind": row["kind"],
                    "canton": row.get("canton"),
                    "bbox": row.get("bbox"),
                    "bbox_crs": "EPSG:4326",
                    "source_layer_id": row["source_layer_id"],
                    "feature_count": row.get("feature_count", 1),
                    "match_score": round(score, 4),
                    "match_basis": basis,
                }
            )
        return results

    def get_division(self, division_ref: str) -> dict[str, Any] | None:
        try:
            position = int(division_ref.removeprefix("division:"))
            row = self.divisions[position]
        except (ValueError, IndexError):
            return None
        if row.get("division_ref") != division_ref:
            return None
        return dict(row)
