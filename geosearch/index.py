"""The vector store: a CPU embedding model, DuckDB for the records, FAISS for the search.

DuckDB holds the records, the three .faiss files hold their vectors, and `meta.model`
records which model produced them - `GeoIndex` refuses to load under a different one,
because cosine similarity between two models' vectors is noise that reads as a working
search. The two are written together by `build` and are only correct together: row `rid`
in DuckDB is vector `rid` in the index, so neither file survives the other being rebuilt.

Layers carry two vectors, title and description, scored as a weighted sum. It is the
design from swisstopo_project/search_data.py and it earns its keep here: a query like
"Wald" matches the *title* of `ch.bafu.landesforstinventar` and the *description* of a
dozen layers that never say "Wald" in their label. One blended vector over
title + description loses that distinction, because a 2000-character abstract drowns a
three-word title.

Index type is IndexFlatIP - exact, no training, no tuning. At ~900 layers and ~2300
divisions an approximate index would trade recall for microseconds nobody will notice.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

import duckdb
import faiss
import numpy as np

logger = logging.getLogger(__name__)

# multilingual-e5-large is the quality option (1024-dim, ~2.2 GB); the MiniLM below is
# ~10x lighter and noticeably faster on CPU. The catalogue is de/fr/it/en/rm, so a
# multilingual model is not optional - an English-only one cannot match "forêt" to
# "Wald".
DEFAULT_MODEL = os.environ.get("GEOSEARCH_EMBED_MODEL", "intfloat/multilingual-e5-large")
LIGHT_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"

INDEX_DIR = Path(os.environ.get("GEOSEARCH_INDEX_DIR", "index"))

# fastembed defaults to tempfile.gettempdir(), which on macOS is a per-boot directory the
# OS sweeps and in a container is a layer that does not survive a restart. Either way the
# 2.2 GB model re-downloads on a cold start. Point it somewhere durable; in production set
# this to a mounted volume so the image does not have to carry the weights.
MODEL_CACHE = Path(os.environ.get("GEOSEARCH_MODEL_CACHE", Path.home() / ".cache" / "fastembed"))

TITLE_WEIGHT = 0.6
DESCRIPTION_WEIGHT = 0.4

# Deliberately low. An absolute cosine floor is not comparable across embedding models
# - 0.55 discards almost nothing under e5 and almost everything under MiniLM - so tuning
# one to taste bakes a model choice into the retrieval logic. This sits low enough to
# only catch "the catalogue has nothing like this", and precision is the reranker's job
# (geosearch/rerank.py). Raising it would trade away the recall FAISS is here to provide.
SIMILARITY_FLOOR = 0.30

# The top hit has to beat the runner-up by this much for the agent to be allowed to
# auto-select it. Ported from search_data.py's confidence gate.
CONFIDENCE_MARGIN = 0.02


@dataclass
class Hit:
    score: float
    row: dict[str, Any]


class Embedder:
    """fastembed on ONNX: CPU-only by design, no torch in the dependency tree."""

    def __init__(self, model_name: str = DEFAULT_MODEL) -> None:
        from fastembed import TextEmbedding

        self.model_name = model_name
        self._model = TextEmbedding(model_name=model_name, cache_dir=str(MODEL_CACHE))
        # e5 models are trained with asymmetric prefixes and lose a lot of retrieval
        # quality without them. fastembed's query_embed/passage_embed do NOT add them
        # (verified: both return identical vectors for the same text), so we do.
        self._e5 = "e5" in model_name.lower()
        self.dim = len(self._encode(["probe"], "query: ")[0])

    def _encode(self, texts: Sequence[str], prefix: str) -> np.ndarray:
        if not texts:
            # A build with no divisions is legitimate (--no-divisions); an empty list
            # would otherwise reach faiss as a 0-d array and raise inside normalize_L2.
            return np.zeros((0, self.dim), dtype=np.float32)
        prepared = [f"{prefix}{t}" if self._e5 else t for t in texts]
        vectors = np.array(list(self._model.embed(prepared)), dtype=np.float32)
        # IndexFlatIP is inner product; on unit vectors that is cosine similarity.
        faiss.normalize_L2(vectors)
        return vectors

    def encode_documents(self, texts: Sequence[str]) -> np.ndarray:
        return self._encode(texts, "passage: ")

    def encode_query(self, text: str) -> np.ndarray:
        vector: np.ndarray = self._encode([text], "query: ")[0]
        return vector


def _flat_index(vectors: np.ndarray) -> faiss.Index:
    index = faiss.IndexFlatIP(vectors.shape[1])
    index.add(vectors)
    return index


def _search(index: faiss.Index, vector: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    if index.ntotal == 0:
        return np.empty(0, dtype=np.float32), np.empty(0, dtype=np.int64)
    scores, ids = index.search(vector.reshape(1, -1), min(k, index.ntotal))
    return scores[0], ids[0]


class GeoIndex:
    """Reads the built index. Construction is cheap; the model load is not, so one
    instance is shared for the life of the server."""

    def __init__(self, directory: Path = INDEX_DIR, embedder: Embedder | None = None) -> None:
        self.directory = Path(directory)
        db_path = self.directory / "geosearch.duckdb"
        if not db_path.exists():
            raise FileNotFoundError(
                f"No index at {db_path}. Build it first: python -m geosearch.build"
            )
        self.db = duckdb.connect(str(db_path), read_only=True)

        stored_model = self.db.execute(
            "SELECT value FROM meta WHERE key = 'model'"
        ).fetchone()
        model_name = stored_model[0] if stored_model else DEFAULT_MODEL
        self.embedder = embedder or Embedder(model_name)
        if self.embedder.model_name != model_name:
            # Vectors from two different models share a space only by coincidence.
            raise ValueError(
                f"Index was built with {model_name!r} but the server loaded "
                f"{self.embedder.model_name!r}. Rebuild the index or set "
                f"GEOSEARCH_EMBED_MODEL={model_name!r}."
            )

        self.layer_title = faiss.read_index(str(self.directory / "layer_title.faiss"))
        self.layer_description = faiss.read_index(str(self.directory / "layer_description.faiss"))
        self.division_name = faiss.read_index(str(self.directory / "division_name.faiss"))

    # ------------------------------------------------------------------ layers

    def search_layers(
        self,
        query: str,
        limit: int = 20,
        queryable_only: bool = False,
    ) -> list[Hit]:
        """Layers ranked by weighted title+description similarity.

        Over-fetches before filtering: asking FAISS for exactly `limit` and then
        dropping the raster layers would return fewer than `limit` usable rows.
        """
        vector = self.embedder.encode_query(query)

        # Both indexes are searched exhaustively (k = ntotal) rather than to some depth.
        # Not a performance oversight: the score is a weighted sum of two similarities,
        # so a layer that ranks well on its title but falls outside a truncated
        # description list would be scored on 0.6 * title alone and lose to a layer
        # present in both lists with two mediocre halves. At 896 x 1024 floats an
        # exhaustive flat scan costs well under a millisecond, and it is what makes the
        # weighting mean what it says.
        combined: dict[int, float] = {}
        for index, weight in (
            (self.layer_title, TITLE_WEIGHT),
            (self.layer_description, DESCRIPTION_WEIGHT),
        ):
            scores, ids = _search(index, vector, index.ntotal)
            for score, rid in zip(scores, ids):
                if rid >= 0:
                    combined[int(rid)] = combined.get(int(rid), 0.0) + weight * float(score)

        ranked = sorted(combined.items(), key=lambda kv: -kv[1])
        hits: list[Hit] = []
        for rid, score in ranked:
            if score < SIMILARITY_FLOOR:
                break
            row = self._layer_row(rid)
            if queryable_only and not row["queryable"]:
                continue
            hits.append(Hit(score=score, row=row))
            if len(hits) >= limit:
                break
        return hits

    def _layer_row(self, rid: int) -> dict[str, Any]:
        row = self.db.execute(
            "SELECT layer_id, title, description, layer_type, topics, attribution, "
            "data_owner, details_url, queryable, displayable FROM layers WHERE rid = ?",
            [rid],
        ).fetchone()
        keys = (
            "layer_id", "title", "description", "layer_type", "topics", "attribution",
            "data_owner", "details_url", "queryable", "displayable",
        )
        if row is None:
            # A FAISS id with no DuckDB row means the index and the database disagree -
            # a stale .faiss beside a rebuilt .duckdb. Say that, rather than raising
            # TypeError from zip() and sending whoever reads it looking in the wrong file.
            raise LookupError(f"layer rid {rid} is in the FAISS index but not in {self.directory}")
        return dict(zip(keys, row))

    # --------------------------------------------------------------- divisions

    def search_divisions(
        self,
        query: str,
        limit: int = 20,
        kinds: Iterable[str] | None = None,
    ) -> list[Hit]:
        """Administrative divisions ranked by name similarity.

        Vector search on names is deliberately forgiving: it resolves "Geneve" to
        "Genève" and "Zurich" to "Zürich", which an exact-match lookup on the
        gazetteer does not.
        """
        vector = self.embedder.encode_query(query)
        wanted = set(kinds) if kinds else None
        scores, ids = _search(self.division_name, vector, max(limit * 5, 100))

        # FAISS does not order exact ties, and since the locality register was added there
        # are thousands of them: "Baar" is a commune *and* a locality, so one name, one
        # vector, one score. Tie-break on rid, which runs coarsest first, so the commune
        # leads its locality instead of whichever the heap happened to pop - an agent that
        # takes the top bbox at face value should get the bigger, safer one.
        ranked = sorted(
            ((float(s), int(r)) for s, r in zip(scores, ids) if r >= 0),
            key=lambda pair: (-pair[0], pair[1]),
        )

        hits: list[Hit] = []
        for score, rid in ranked:
            if score < SIMILARITY_FLOOR:
                continue
            row = self._division_row(rid)
            if wanted and row["kind"] not in wanted:
                continue
            hits.append(Hit(score=float(score), row=row))
            if len(hits) >= limit:
                break
        return hits

    def _division_row(self, rid: int) -> dict[str, Any]:
        row = self.db.execute(
            "SELECT name, kind, canton, bbox, layer_id, s3_key, feature_count "
            "FROM divisions WHERE rid = ?",
            [rid],
        ).fetchone()
        keys = ("name", "kind", "canton", "bbox", "layer_id", "s3_key", "feature_count")
        if row is None:
            raise LookupError(f"division rid {rid} is in the FAISS index but not in {self.directory}")
        out = dict(zip(keys, row))
        out["bbox"] = list(out["bbox"]) if out["bbox"] is not None else None
        return out

    def division_by_name(self, name: str, kind: str | None = None) -> dict[str, Any] | None:
        sql = "SELECT rid FROM divisions WHERE lower(name) = lower(?)"
        params: list[Any] = [name]
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        # One name can be four levels at once - Zürich is a canton, a district, a commune
        # and a locality. rid follows DIVISIONS, which is ordered coarsest first, so an
        # unqualified name draws the largest thing that bears it. Ordering explicitly
        # because it is a behaviour, not an accident of insertion.
        sql += " ORDER BY rid LIMIT 1"
        row = self.db.execute(sql, params).fetchone()
        return self._division_row(row[0]) if row else None

    def counts(self) -> dict[str, int]:
        def one(sql: str) -> int:
            row = self.db.execute(sql).fetchone()
            return int(row[0]) if row else 0

        return {"layers": one("SELECT count(*) FROM layers"),
                "divisions": one("SELECT count(*) FROM divisions")}


def confidence(hits: Sequence[Hit]) -> dict[str, Any]:
    """Whether the top hit is a clear winner.

    search_data.py's rule, and it matters more here than there: when a query has no good
    answer in the catalogue the scores bunch up just above the floor, and a model handed
    a ranked list with no confidence signal will pick row one and present it as *the*
    dataset. Told the margin is thin, it asks instead.
    """
    if not hits:
        return {"top_score": None, "margin": None, "low_confidence": True}
    top = hits[0].score
    margin = top - hits[1].score if len(hits) > 1 else top
    return {
        "top_score": round(top, 4),
        "margin": round(margin, 4),
        "low_confidence": margin < CONFIDENCE_MARGIN,
    }


# ------------------------------------------------------------------- building


def build(
    directory: Path,
    layers: list[dict[str, Any]],
    divisions: list[dict[str, Any]],
    embedder: Embedder,
    reuse_layer_vectors: bool = False,
) -> dict[str, int]:
    """Writes geosearch.duckdb and the three FAISS indexes. Overwrites any existing build."""
    directory.mkdir(parents=True, exist_ok=True)
    db_path = directory / "geosearch.duckdb"
    db_path.unlink(missing_ok=True)
    db = duckdb.connect(str(db_path))

    db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    db.execute("INSERT INTO meta VALUES ('model', ?)", [embedder.model_name])

    db.execute(
        """CREATE TABLE layers (
            rid INTEGER PRIMARY KEY, layer_id TEXT, title TEXT, description TEXT,
            layer_type TEXT, topics TEXT, attribution TEXT, data_owner TEXT,
            details_url TEXT, queryable BOOLEAN, displayable BOOLEAN
        )"""
    )
    for rid, rec in enumerate(layers):
        db.execute(
            "INSERT INTO layers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                rid, rec["layer_id"], rec["title"], rec["description"], rec["layer_type"],
                rec["topics"], rec["attribution"], rec["data_owner"], rec["details_url"],
                rec["queryable"], rec["displayable"],
            ],
        )

    db.execute(
        """CREATE TABLE divisions (
            rid INTEGER PRIMARY KEY, name TEXT, kind TEXT, canton TEXT,
            bbox DOUBLE[4], layer_id TEXT, s3_key TEXT, feature_count INTEGER
        )"""
    )
    for rid, rec in enumerate(divisions):
        db.execute(
            "INSERT INTO divisions VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                rid, rec["name"], rec["kind"], rec.get("canton"), rec.get("bbox"),
                rec["layer_id"], rec.get("s3_key"), rec.get("feature_count", 1),
            ],
        )
    db.close()

    if reuse_layer_vectors:
        dim = _check_layer_vectors(directory, layers, embedder)
    else:
        logger.info("embedding %d layer titles", len(layers))
        titles = embedder.encode_documents([r["title"] for r in layers])
        logger.info("embedding %d layer descriptions", len(layers))
        # A layer with no abstract falls back to its title. The alternative - a zero vector -
        # would score 0 on the description half and push it below the floor for every query,
        # making it permanently unfindable.
        descriptions = embedder.encode_documents(
            [r["description"] or r["title"] for r in layers]
        )
        faiss.write_index(_flat_index(titles), str(directory / "layer_title.faiss"))
        faiss.write_index(_flat_index(descriptions), str(directory / "layer_description.faiss"))
        dim = int(titles.shape[1])

    logger.info("embedding %d division names", len(divisions))
    names = embedder.encode_documents([r["name"] for r in divisions])
    faiss.write_index(_flat_index(names), str(directory / "division_name.faiss"))

    return {"layers": len(layers), "divisions": len(divisions), "dim": dim}


def _check_layer_vectors(directory: Path, layers: list[dict[str, Any]], embedder: Embedder) -> int:
    """Confirm the layer vectors already on disk still describe these catalogue rows.

    Embedding 896 abstracts is 20 of the build's 25 minutes and none of it changes when
    only the divisions do, so `--reuse-layer-vectors` keeps the existing indexes. What
    makes that safe to offer is this check: a vector that no longer matches its row is not
    an error anywhere downstream, it is a search that quietly ranks the wrong layer first.
    A spread of rows is re-embedded and compared rather than trusted.
    """
    stored = {}
    for name in ("layer_title", "layer_description"):
        path = directory / f"{name}.faiss"
        if not path.exists():
            raise ValueError(f"--reuse-layer-vectors needs {path}, which does not exist")
        stored[name] = faiss.read_index(str(path))
        if stored[name].ntotal != len(layers):
            raise ValueError(
                f"{path.name} holds {stored[name].ntotal} vectors but the catalogue has "
                f"{len(layers)} layers - rebuild without --reuse-layer-vectors"
            )

    index = stored["layer_title"]
    picks = list(range(0, len(layers), max(1, len(layers) // 8)))[:8]
    fresh = embedder.encode_documents([layers[i]["title"] for i in picks])
    on_disk = np.vstack([index.reconstruct(i) for i in picks])
    drift = float(np.abs(fresh - on_disk).max())
    if drift > 1e-4:
        raise ValueError(
            f"the layer vectors in {directory} do not match the catalogue (drift {drift:.3g}) - "
            "rebuild without --reuse-layer-vectors"
        )
    logger.info("reusing %d layer vectors (drift %.2g)", index.ntotal, drift)
    return int(index.d)
