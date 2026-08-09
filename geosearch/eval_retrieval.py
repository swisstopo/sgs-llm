"""Retrieval quality of a built index, and what SIMILARITY_FLOOR should be for it.

Run this after any change to the embedding model. Both numbers it reports are properties
of the model, not of this code, and neither survives a model swap:

  * recall@30 is the one that matters. 30 is what the reranker sees, so a gold layer
    outside it is unreachable however good the LLM stage is. Switching from
    multilingual-e5-large to Cohere Embed v4 moved `peat bogs` from rank 186 to rank 2.

  * SIMILARITY_FLOOR is an absolute cosine value, and absolute cosine is not comparable
    across models. 0.30 discarded almost nothing under e5; under Cohere the same 0.30 cut
    the candidate list to a median of 5 and left a gold layer alive at 0.311. A layer cut
    by the floor is not ranked low, it is absent, so this is a silent failure by default.

    .venv/bin/python -m geosearch.eval_retrieval
"""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np

from .index import DESCRIPTION_WEIGHT, INDEX_DIR, SIMILARITY_FLOOR, TITLE_WEIGHT, GeoIndex, _search

# 12 known-answer queries across de/fr/it/en - the catalogue is multilingual, and a model
# that only works in one of them fails invisibly for the others. Gold is a set of
# layer_ids: some concepts legitimately name more than one layer. Ids rather than rids,
# because a rid is positional and a benchmark pinned to one silently scores the wrong
# layer after the next rebuild.
GOLD: list[tuple[str, str, set[str]]] = [
    ("Waldmischungsgrad", "de", {"ch.bafu.landesforstinventar-waldmischungsgrad"}),
    ("avalanches", "fr", {"ch.bafu.silvaprotect-lawinen"}),
    ("glacier extent", "en", {"ch.swisstopo.geologie-gletscherausdehnung"}),
    ("terremoti storici", "it", {"ch.bafu.gefahren-historische_erdbeben"}),
    ("zones sismiques", "fr", {"ch.bafu.gefahren-gefaehrdungszonen"}),
    ("peat bogs", "en", {"ch.bafu.bundesinventare-hochmoore", "ch.bafu.bundesinventare-flachmoore"}),
    ("arsenico nel suolo", "it", {"ch.bafu.geochemischer-bodenatlas_schweiz_arsen"}),
    ("population inhabitants", "en", {"ch.bfs.volkszaehlung-bevoelkerungsstatistik_einwohner"}),
    ("réserves d'oiseaux migrateurs", "fr", {"ch.bafu.bundesinventare-vogelreservate"}),
    ("snowshoe trails", "en", {"ch.astra.schneeschuhwanderwege"}),
    ("statistica delle piene", "it", {"ch.bafu.hydrologie-hochwasserstatistik"}),
    ("Personenverkehr Schiene", "de", {"ch.are.belastung-personenverkehr-bahn"}),
]

# Queries with no answer anywhere in a Swiss geodata catalogue. The floor's entire job is
# to separate these from the ones above; if it cannot, it is the wrong instrument and
# should be lowered until the reranker's "none of these fit" carries the decision instead.
NONSENSE = [
    "risotto recipe with saffron",
    "bitcoin price history",
    "how do I reset my password",
    "premier league fixtures",
    "quarterly revenue forecast",
]


def blended_scores(index: GeoIndex, query: str) -> np.ndarray:
    """Every layer's weighted title+description score, floor and limit bypassed.

    search_layers cannot be used here: it applies the floor, which is the thing being
    measured, and it returns rows rather than the full distribution.
    """
    vector = index.embedder.encode_query(query)
    total = np.zeros(index.layer_title.ntotal, dtype=np.float64)
    for faiss_index, weight in (
        (index.layer_title, TITLE_WEIGHT),
        (index.layer_description, DESCRIPTION_WEIGHT),
    ):
        scores, ids = _search(faiss_index, vector, faiss_index.ntotal)
        total[ids] += weight * scores
    return total


def main(directory: Path = INDEX_DIR) -> None:
    index = GeoIndex(directory)
    layer_ids = [
        row[0]
        for row in index.db.execute("SELECT layer_id FROM layers ORDER BY rid").fetchall()
    ]
    print(f"{directory}: {index.counts()}, model {index.embedder.model_name}\n")

    recall_8 = recall_30 = mrr = 0.0
    latencies: list[float] = []
    real: list[np.ndarray] = []
    for query, lang, gold in GOLD:
        started = time.perf_counter()
        scores = blended_scores(index, query)
        latencies.append((time.perf_counter() - started) * 1000)
        real.append(scores)

        order = np.argsort(-scores)
        found = [i for i, rid in enumerate(order) if layer_ids[rid] in gold]
        best = min(found) if found else None
        recall_8 += best is not None and best < 8
        recall_30 += best is not None and best < 30
        mrr += 1.0 / (best + 1) if best is not None else 0.0
        print(f"  {lang} {query:32} rank {best + 1 if best is not None else '-':>4}"
              f"  score {scores[order[best]] if best is not None else 0:.3f}")

    n = len(GOLD)
    print(f"\nrecall@8={recall_8 / n:.2f} recall@30={recall_30 / n:.2f} MRR={mrr / n:.3f} "
          f"query={np.median(latencies):.0f}ms\n")

    junk = [blended_scores(index, query) for query in NONSENSE]
    print(f"best score, real queries:     min {min(s.max() for s in real):.3f}  "
          f"median {np.median([s.max() for s in real]):.3f}")
    print(f"best score, nonsense queries: max {max(s.max() for s in junk):.3f}")
    print("\nThe floor belongs in the gap between those two lines.")
    for floor in sorted({SIMILARITY_FLOOR, 0.30, 0.25, 0.20, 0.15}, reverse=True):
        kept = [int((s >= floor).sum()) for s in real]
        leaked = [int((s >= floor).sum()) for s in junk]
        mark = "  <- current" if floor == SIMILARITY_FLOOR else ""
        print(f"  floor {floor:.2f}: real keep {min(kept)}-{max(kept)} "
              f"(median {int(np.median(kept))}), nonsense keep {min(leaked)}-{max(leaked)}{mark}")


if __name__ == "__main__":
    main()
