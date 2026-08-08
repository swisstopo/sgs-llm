# geosearch

Semantic search over the swisstopo catalogue, and the MCP server that serves it.

```bash
python -m geosearch.build      # once: fetch, embed, index (~25 min with e5-large)
python -m geosearch.build --reuse-layer-vectors   # divisions only (~90 s)
python -m geosearch.server     # http://127.0.0.1:8790/mcp
python -m pytest geosearch/test_geosearch.py -q
```

## Why this exists

The previous `search_layers` forwarded the query to geo.admin.ch's SearchServer. Measured
against the live API on 2026-08-06:

- The tool hardcoded `limit=8`. For "Wald" there are **13 queryable forest layers; only 2
  appeared in the top 8.** Eleven were invisible to the agent.
- Relevance decayed hard — ranks 25-30 for "Wald" returned `Milchmarktregionen`,
  `Bezirksgrenzen`, `Jagdbanngebiete`.
- Matching was lexical, so it was language-bound: `Wald` (de) surfaced 2 queryable layers,
  `forêt` (fr) surfaced 4 — different sets, same question.
- `identify` caps a response at 200 features and the tool asked for one page, so a canton
  query silently truncated. Observed live: the same Zug query returned 50 features once
  and 46 later, and the model reported the cap as a total ("50 Messstationen im Kanton
  Bern").

Vector search fixes the recall and language problems; the LLM filter fixes the precision
that vector search alone gives up; grid-subdivided identify fixes the cap.

## How it works

```
build (once)                          serve (per query)
──────────                            ─────────────────
layersConfig ─┐                       query
              ├─► 896 records ─┐        │ embed (~60 ms CPU)
api/MapServer ┘   title+abstract│        ▼
                                ├─►   FAISS ── 30 candidates ─► LLM filter ─► 8 results
swissBOUNDARIES3D ─┐            │     (exhaustive,             (cheap model,
 land/kanton/      ├─► 6272     │      weighted 0.6/0.4)        drops near-misses)
 bezirk/gemeinde   │  divisions │
Ortschaftenverz. ──┘     │      │
                         ├──────┘
                         ├─► names
                         └─► polygons ─► S3
```

DuckDB holds the records, the three FAISS files hold their vectors, and row `rid` in one
is vector `rid` in the other. They are written together by a single build and are only
correct together — rebuilding either alone silently misaligns every result.

## Decisions worth knowing

**Two vectors per layer, not one.** Title and description are embedded separately and
scored `0.6 * title + 0.4 * description` (the design in `search_data.py`). Blending them
into one vector loses the distinction: a 2000-character abstract drowns a three-word
title. "Wald" matches the *title* of one layer and the *description* of a dozen others,
and both matter.

**Both indexes are searched exhaustively (`k = ntotal`).** Not an oversight. With a
truncated depth, a layer ranking well on title but outside the description's top-K scored
`0.6 × title` alone and lost to a layer present in both lists with two mediocre halves.
At 896 × 1024 floats a flat scan is well under a millisecond. `test_score_sums_both_halves_not_just_one` pins this.

**The similarity floor is low (0.30) on purpose.** An absolute cosine floor is not
comparable across embedding models — 0.55 discards almost nothing under e5 and almost
everything under MiniLM — so tuning one to taste bakes a model choice into the retrieval
logic. It exists only to detect "the catalogue has nothing like this". Precision is the
reranker's job.

**The LLM filter fails open — but only for unreachability.** If Bedrock cannot be
reached the vector ranking is returned with a note telling the agent it is unfiltered; a
degraded search beats a broken one. It is deliberately narrow. `_parse` keeps `[]` ("none
of these fit") distinct from `None` (nothing parsed), because collapsing them turns a
correct rejection into four confidently-wrong results. That distinction is what exposed a
greedy-regex bug: ministral answers a no-match query with `[]` followed by the same array
in a fence, and `\[.*\]` spanned both into invalid JSON.

**Every fetch is pinned to one time instant.** 59 of the 896 catalogue layers are
time-enabled, and `identify` returns *every* vintage of every feature unless `timeInstant`
says otherwise — the commune layer carries 177, back to 1850. Nothing downstream can tell a
vintage from a neighbour, so `filter_features` reported 1228 communes in a box holding 7 and
`compute` summed their areas to 24104 km², more than half of Switzerland. `fetch_features`
now pins the layer's newest published timestamp for every caller. Two traps here: the bug is
invisible on point layers, where the inflated area is `0.0` and looks right; and
`is_current_jahr` reads like the correct filter but is False on the previous year's rows
too, so it silently returns nothing whenever the newest vintage is not the current year.

**A place is a polygon, not its bounding box.** `filter_features` takes `place` +
`place_kind` from search_locations and cuts the answer to the real boundary, which the
build already downloaded — so this costs no network call. A bbox is a rectangle drawn
around a place, and everything in the corners belongs to somewhere else. Measured live
against the commune layer:

| scoped by | canton Zug | canton Genève |
|---|---|---|
| `bbox` | 42 communes over LU/SZ/ZG/AG/ZH, 808 km² | 57 communes over GE/VD, 345 km² |
| `place` | **11 communes, 239 km²** | **45 communes, 282 km²** |

(Zug is 11 communes and 239 km²; Genève is 45 and 282.) Nothing downstream can correct
this — a neighbouring commune is the same dataset with the same attributes as a member —
so it has to happen while the boundary is still in hand. Features are *cut*, not merely
kept, because a river or a forest that crosses the border belongs to the place only in
part: veloland in canton Zug is 512 km of routes by bbox and 147 km clipped. `bbox` is
still accepted, for an area with no name such as the map view the user is looking at.

**Clipping drops the slivers two datasets leave at their shared edge.** The postcode
register and swissBOUNDARIES3D are surveyed and maintained separately, so their common
boundaries do not agree to the metre: clipping the commune layer to the locality of Wengen
leaves 22 m² of Grindelwald beside 34 km² of Lauterbrunnen, and "Wengen lies in two
communes" is a wrong answer produced entirely by rounding. A feature keeping less than a
millionth of itself is discarded — far below any real overlap, far above these. Border-only
contact is discarded by the same logic one step earlier: two polygons that share an edge
intersect in a *line*, and every commune along a canton border produces one.

**Confidence is reported, not hidden.** When scores bunch up, `low_confidence` is set and
the tool docstring tells the model not to silently pick rank 1. Handed a ranked list with
no confidence signal, models present the first row as *the* answer.

**Places resolve five levels deep, not three.** The index holds Switzerland itself, 26
cantons, 135 districts, 2136 commune-layer rows and 3974 localities — 6272 in all. The
locality register (`ortschaftenverzeichnis_plz`) is the one that matters most: **2302 of
its names are not the name of any commune**, so without it "Wengen", "Gstaad", "Verbier"
and "Davos Platz" resolve to nothing at all. It is also the one level that is not
one-polygon-per-place — a locality is one polygon per postcode, and Zürich has 24 — so
`fetch_divisions` returns a *group* of features per name. Keeping only the first would
have put an eighth of the city on the map and labelled it Zürich.

**The country layer is filtered to Switzerland.** It carries four territories: Schweiz
plus the three foreign bodies that touch it. Two of those are enclaves — "Italia" is
Campione d'Italia at 2.6 km² and "Deutschland" is Büsingen at 7.6 km² — so publishing
them under those names would resolve a question about Germany to a village-sized polygon.
Liechtenstein is genuinely the whole principality, but it is not Switzerland and its 11
municipalities are already in the commune layer.

**Districts and localities get their canton from geometry.** Neither carries one: the
district layer's only properties are `name`, `label` and `flaeche`. Left as the source
has them, 4109 of 6272 rows would report `canton: null` — and `canton` is the field an
agent uses to tell one Aesch from another. The build indexes the canton polygons in an
STRtree and looks each one up by representative point (not centroid: Swiss communes are
concave enough for a centroid to land outside its own polygon). The 27 rows that still
come back null are correct — Switzerland is in no canton, and the rest are Liechtenstein,
Campione and Büsingen.

**The commune layer is not only communes.** Of its 2136 rows, 2123 are `gemeindegebiet`;
the rest are the large lakes, two `kommunanz` shared territories and Staatswald Galm,
which belong to no commune. One of them — the lake Greifensee — shares its name with a
commune, so deduping on the name alone silently kept whichever identify returned first
(observed: the lake) and made the commune unreachable. The dedup key and the stored `kind`
both come from `objektart_lookup`.

**One name at several levels ranks coarsest first.** "Baar" is a commune *and* a locality:
one name, one vector, one score — and FAISS does not order exact ties, so which one led
was whatever the heap happened to pop. `search_divisions` breaks ties on `rid`, which the
build writes coarsest first, and `division_by_name` orders the same way. An agent that
takes the top bbox at face value gets the larger, safer one.

**`--reuse-layer-vectors` skips the 20 minutes that never change.** Embedding 896 abstracts
is most of the build and none of it moves when only the divisions do. The flag keeps the
existing layer indexes — but a vector that no longer matches its row is not an error
anywhere downstream, it is a search that quietly ranks the wrong layer first, so the build
re-embeds a spread of titles and refuses to reuse anything that has drifted (or whose count
disagrees with the catalogue). Verified against the real catalogue: drift 0.

**Z is stripped from every geometry.** swissBOUNDARIES3D is 3D. `LayerService.ts` hands
everything to OpenLayers as EPSG:4326, which reads a third ordinate as data and reprojects
nonsense rather than failing — an invisible corruption, so it is tested at every nesting
depth.

## Embedding model

CPU-only via fastembed (ONNX, no torch). Multilingual is not optional: the catalogue is
de/fr/it/en/rm, and an English-only model cannot match "forêt" to "Wald". fastembed ships
exactly three genuinely multilingual models; two were measured on 12 known-answer queries
across de/fr/it/en (`GOLD` in the eval script — each names a concept with an
exactly-matching layer):

| | dim | recall@8 | recall@30 | MRR | query | build | RSS |
|---|---|---|---|---|---|---|---|
| `intfloat/multilingual-e5-large` (default) | 1024 | **1.00** | 1.00 | 0.815 | 31 ms | ~40 min | ~2.2 GB |
| `paraphrase-multilingual-MiniLM-L12-v2` | 384 | 0.67 | 0.67 | 0.627 | 22 ms | ~25 s | ~0.4 GB |

**recall@30 is the column that settled it.** 30 is what the reranker sees, so a gold layer
outside it is unreachable no matter how good the LLM stage is — and MiniLM's recall@30 is
identical to its recall@8. Its four failures are not near-misses the second stage could
fix; the right layer is simply never retrieved. For the exact query "Waldmischungsgrad" it
scored `Vereisungshäufigkeit` at 0.809 against `Waldmischungsgrad LFI` at 0.623: a
paraphrase-trained model matching German compound morphology rather than meaning.

Those are vector-only figures. Re-run through the live server — vector retrieval *and* the
LLM reranker together, which is what an agent actually sees — the same 12 queries score
**12/12, gold at rank 1 for eleven of them**, in 411–745 ms including the Bedrock round-trip.
Worth measuring separately: a second stage that prunes can just as easily discard what the
first stage got right, and recall@8 alone would not show it.

The cost is build time and memory, not latency — 31 ms per query, because a query is ten
tokens while the 896 abstracts that make the build slow are up to 512 each. If rebuilds
become a bottleneck, truncating descriptions before embedding is the lever to pull (the
reranker already reads only the first 300 characters); it was not needed to reach 1.00.

Switch with `GEOSEARCH_EMBED_MODEL`. The index records which model built it and refuses to
load under a different one — cosine similarity between two models' vectors is noise, and it
looks exactly like a working search.

The weights land in `GEOSEARCH_MODEL_CACHE` (default `~/.cache/fastembed`). fastembed's own
default is `tempfile.gettempdir()`, which macOS sweeps and a container discards on restart —
either way the 2.2 GB re-downloads on every cold start. The image bakes them in instead; see
below.

e5 needs `query:` / `passage:` prefixes to retrieve well. fastembed's `query_embed` and
`passage_embed` do **not** add them (verified: both return identical vectors for the same
input), so `Embedder` adds them.

## S3

Two different things get called "storage" here, and separating them is what makes the
deployment simple.

**Published layers** — the GeoJSON an answer produces — go to S3 through ordinary boto3,
to `sgs-llm-data-259789526488` under `layers/`. `S3Store` is used either way: set
`GEOSEARCH_S3_BUCKET` and the calls go to real S3, leave it unset and
`GEOSEARCH_S3_ENDPOINT` points the identical calls at an in-process moto server — no
Docker, no daemon. moto is in `requirements-dev.txt`, not `requirements.txt`, so the
deployed image ships no test double; `infra/geosearch-foundation.yaml`'s task role is what
made that possible. It grants `GetObject` as well as `PutObject`, because a presigned URL
carries the signer's permissions and every map layer would otherwise 403 in the browser.

`ensure_bucket` (create + open CORS) is a deliberate no-op against real S3: that bucket is
managed by CloudFormation with public access blocked on all four settings, and an
application quietly rewriting its CORS policy is how a private bucket becomes a public one.

**Division boundaries** are not that. They are build output — 6272 polygons that change
when `build` runs and at no other time — so they are read off disk by `BoundaryStore` and
ship inside the image. Keeping them in the data bucket instead would have put them under
its `expire-data-layers` lifecycle rule (`infra/backend-foundation.yaml`, 30 days, no
prefix filter), and `display_division` would have started 404-ing one place at a time after
a month. The rule is right for published layers; the boundaries were simply the wrong thing
to keep beside them.

## Deployment

Everything expensive is precomputed and copied in. `geosearch/Dockerfile` never runs
`build`: that is ~25 minutes and a few thousand requests to geo.admin.ch, and two runs a
week apart produce two different indexes, which is the opposite of an image.

| what | size | where it comes from |
|---|---|---|
| `index/*.duckdb`, `index/*.faiss` | 36 MB | `python -m geosearch.build`, copied in |
| `index/s3/` (boundaries) | 108 MB | same build, copied in |
| e5-large ONNX weights | 2.1 GB | `RUN` step, baked at image build |
| layer catalogue (`timeInstant`, WMS config) | — | **fetched at runtime**, not frozen |

So the image is ~3 GB and takes 2–3 minutes for Fargate to pull, against a cold start that
would otherwise download 2.1 GB before answering its first request — and would do it again
on every task replacement. Baking it also makes the image the whole contract: the running
container needs no network except geo.admin.ch and S3.

That last row is the one to keep in mind. `Swisstopo.layers_config` is fetched from
geo.admin.ch on first use and memoised per process, so a six-month-old image still queries
today's data at today's vintages. Only the *searchable set* of layers is as of the build —
a layer swisstopo added last week is not in the index and cannot be found until a rebuild.

```
python -m geosearch.build                       # once, ~25 min, writes index/
docker build -f geosearch/Dockerfile -t sgs-llm-geosearch .
docker run -p 8790:8790 sgs-llm-geosearch       # /mcp, plus /health for the orchestrator
```

### On AWS

`infra/geosearch-foundation.yaml` and `infra/geosearch-service.yaml`, split for the same
reason the backend's are: a service cannot be created before an image exists in ECR. They
consume the backend foundation's VPC, subnets, task security group and data-layer bucket,
and create no network topology.

It is a **second service in the backend's existing `sgs-llm` cluster**, not a new one:
`geosearch-service.yaml` takes `ClusterName` as a string and references the cluster
`backend-service.yaml` creates. On Fargate a cluster owns no capacity and costs nothing, so
a second one would split the metrics and the CLI invocations while isolating nothing.
What does isolate the two is separate everywhere it counts — task definitions, task roles,
security groups, log groups, ECR repositories, deploy roles and stacks.

Three things are deliberately unlike the backend:

**No load balancer.** The only client is the backend task, in the same VPC, so the service
registers in a Cloud Map private namespace and the backend reaches it at
`http://sgs-llm-geosearch.sgs-llm.local:8790/mcp` — the foundation stack's `McpServerUrl`
output, and what `backend-service.yaml`'s `McpServerUrl` parameter should be set to. An
internal ALB would be ~$16/month to say what a DNS record says. The security group admits
the backend's security group and nothing else: no browser ever calls this server, and
`result_id` handles would be a data leak if one could — they name results the caller never
fetched.

**One task, and deploys 0/100 rather than 100/200.** `result_id` handles live in the
`ResultCache` inside one process, so a second task would answer `compute` with "unknown
result_id" for half the handles it just issued. `DesiredCount` is capped at 1 and a rolling
deploy stops the old task before starting the new one. The cost is a gap of a minute or two
per deploy; the alternative is an answer that silently cannot find the features
`filter_features` just returned. Raising this needs a shared result store or sticky
routing first.

**Its own index bucket.** `sgs-llm-index-<account>`, versioned, no expiry — separate from
the data-layer bucket, which deletes everything after 30 days.

```
python -m geosearch.build
aws s3 sync index/ s3://sgs-llm-index-<account>/index/ --delete   # publish
PROFILE=swisstopo ./scripts/deploy-geosearch.sh                   # fetch, build, push, roll
```

`.github/workflows/geosearch.yml` does the same automatically on any change under
`geosearch/`: ruff and the tests always, then build, smoke-test and deploy once the
repository variable `GEOSEARCH_INDEX_URI` names the published prefix (the foundation
stack's `IndexUri` output). Until it is set the deploy job skips loudly rather than passing
on an image it never built — `index/` is gitignored, and CI cannot reproduce it.

## Tools

Same six-tool surface as `mcp_dummy` so the backend and eval harness need no changes, plus
`display_division`.

| tool | change |
|---|---|
| `search_layers` | FAISS + LLM filter instead of SearchServer; returns `similarity`, `low_confidence` |
| `search_locations` | pre-embedded divisions; resolves "Zurich" → "Zürich", and localities as well as communes |
| `display_division` | new — puts a stored boundary on the map, no network call |
| `filter_features` | grid-subdivided identify: a real total, not a capped page; takes `place` and clips to the boundary instead of the bbox |
| `display_catalog_layer`, `compute`, `display_layer` | unchanged |

## Known limits

- `ResultCache` is per-process and in-memory, so `result_id` does not survive a restart or
  reach a second instance. Fine single-instance; needs sticky sessions or a shared store
  before scaling out.
- The index is built for one language at a time (`--lang`, default `de`). The embedding
  model is multilingual, so a German index answers French queries; a per-language index
  would still rank better.
- Rebuilding is manual. The catalogue changes slowly, but nothing currently notices when
  it does.
