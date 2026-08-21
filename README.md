# SGS LLM

Conversational chat and web map application for Swiss federal geodata.

## Description

SGS LLM is an open-source prototype for making Swiss federal geodata accessible to
non-experts through natural language. The application combines a conversational interface,
an interactive web map, Swisstopo API connectors, and LLM-based orchestration so users can
discover, query, and visualize official geodata without needing GIS expertise.

The project is developed in the context of the Swiss Geoinformation Strategy (SGS). It
explores how conversational access, MCP-compatible connectors, and agent-based workflows can
support future Swiss geodata services. The prototype is hosted on Swisstopo's GitHub
organization and is intended to run on Swisstopo infrastructure.

## Status

This repository contains the runnable chat + web map application (`frontend/`) and the
**agent backend** (`backend/`) it talks to over a versioned WebSocket protocol
([`docs/protocol.md`](docs/protocol.md)). The frontend also calls the public Swisstopo APIs
directly for map interactivity.

- **`backend/`** - Python service running the LLM loop on Amazon Bedrock and the MCP client
  for the geodata tools, plus feedback and conversation-turn persistence. See
  [`docs/architecture.md`](docs/architecture.md#backend-architecture).
- **`geosearch/`** - the geodata **MCP server** the chat answers from: semantic search over
  all 896 catalogue layers, precise address and point lookup, complete point identify,
  administrative boundaries from swissBOUNDARIES3D, schema-validated filtering, spatial
  analysis, and map-ready official or personalized layers.
  Deployed as its own service ([`geosearch/README.md`](geosearch/README.md)).
- **`exploration-mcp/`** - a portable, stateless and read-only **public MCP server** for
  dataset discovery, administrative divisions, geocoding, GeoAdmin preview links, and
  parcel/ÖREB point exploration. It has no model or AWS-service dependency and is mounted
  into the existing backend task for general MCP clients at
  [`https://denpw8uo5zpkl.cloudfront.net/mcp`](https://denpw8uo5zpkl.cloudfront.net/mcp)
  ([`exploration-mcp/README.md`](exploration-mcp/README.md),
  [`deployment`](docs/exploration-mcp-deployment.md)).
- **`mcp_dummy/`** - a stand-in geodata MCP server whose tools are backed by the **real**
  geo.admin.ch APIs. It predates `geosearch/` and now serves development and evaluation
  only - **not** production traffic ([`mcp_dummy/README.md`](mcp_dummy/README.md)).
- **`evals/`** - a user-perspective question set and runner that doubles as a **side-by-side
  benchmark of the two pilot models** ([`docs/evals.md`](docs/evals.md)).
- **`mock-agent/`** - the protocol reference implementation, kept as a local test double and
  deployment rollback image.

The AWS infrastructure - ECS Fargate, ALB, Bedrock access, DynamoDB, S3 - is deployed
([`infra/`](infra/), [`docs/deployment.md`](docs/deployment.md#backend-deployment)). This is
a prototype - not for operational use; interfaces and layout may still change.

> **The chat needs `MCP_SERVER_URL`.** The geodata server is [`geosearch/`](geosearch/README.md);
> pointing that one variable at it turns the chat on. With it unset the backend accepts
> WebSocket connections and refuses every turn rather than substituting the bundled
> stand-in, so nothing can mistake development output for production data. The map is a
> separate track and is fully usable meanwhile - see
> [`docs/protocol.md`](docs/protocol.md#waiting-for-the-production-mcp-server).

> **Model note.** The pilot's primary model is Claude Sonnet 4.6 via a Bedrock EU inference
> profile, with `mistral.ministral-3-14b-instruct` in `eu-west-1` as the secondary. Both the
> organization SCP and the Anthropic use-case gate that blocked Claude are now clear -
> Sonnet 4.6 and Sonnet 5 both answered from `eu-central-1` on 2026-08-10. A process started
> before that clears keeps using the secondary until restarted - see
> [`docs/llm.md`](docs/llm.md).

A live POC instance (frontend + agent backend + geosearch MCP) is available at
**https://denpw8uo5zpkl.cloudfront.net/**. See [Deployment](#deployment).

## Features

- **Swiss map projection (LV95)** — the map renders in EPSG:2056 on the official swisstopo
  zoom ladder (650 → 0.25 m/px), so the national map appears as the familiar clean rectangle:
  zoomed out you get the generalized country view including the neighboring borders, zooming
  in reveals the detailed map styles — exactly as on map.geo.admin.ch / SwissGeo
- **All catalog layer types render** — official layers are added as WMTS tiles, WMS
  (tiled or single-image, per the layer's config), or GeoJSON vector layers styled with the
  official geoadmin style definitions; live GeoJSON layers (e.g. rain radar, flood gauges)
  re-fetch themselves on the layer's update interval. Only genuinely non-displayable catalog
  entries are greyed out
- **SwissGeo-style shell** — a left icon rail; clicking an icon slides its flyout panel in as
  an animated overlay over the map (one open at a time, resizable by dragging its right edge):
  - **Chat** — natural-language conversation with streamed tool-progress, sanitized markdown
    answers, and data layers rendered on the map; exact official layer titles open an inline
    add/remove/details control, while personalized points, parcels, boundaries, and filtered
    results use a separate **Show result on map** card; a "+" button starts a new conversation
  - **Displayed maps** — three Swisstopo basemaps (color / grey / aerial) and the active
    layer list with visibility, opacity, drag-and-drop ordering, zoom-to-extent, per-layer
    information, and a hint when many layers are active
  - **Geocatalog** — the official Swisstopo catalog tree (CatalogServer): topic selector with
    translated topic names, in-tree filter, add/remove layers, and a per-layer info button
  - **Feedback** — a feedback form posted to a configurable endpoint
  - **About** — project, partners, and data-source information
- **Map controls** — a SwissGeo-style bottom-right cluster: a geolocation button (with
  Swiss-bounds check and position marker) above the zoom in/out bar
- **Layer information** — every layer (in the panel and the catalog) opens a dialog with the
  official swisstopo description, legend, data owner, and geocat/download links
- **Automatic legends** — while a layer with a legend is visible, its official Swisstopo legend
  appears in a panel at the map's top-right, and disappears when the layer is hidden or removed
- **Identify on click** — feature attributes from the MapServer identify endpoint (queried in
  LV95), with an LV95 coordinate readout
- **Multilingual** — German, French, Italian, English, and Romansh; the active language is
  passed to every Swisstopo API call and chat message
- **Lean live connectors** — thin, typed wrappers over the public geo.admin.ch APIs with
  request timeouts, cancellation of superseded requests, and the API's paging/word limits
  respected (see [`docs/architecture.md`](docs/architecture.md))

## Architecture overview

```text
Browser (frontend/, Lit + OpenLayers + @swissgeol/ui-core, map in EPSG:2056)
  ├── direct calls ─────────────►  Swisstopo public APIs
  │                                (api3.geo.admin.ch, wmts.geo.admin.ch,
  │                                 wms.geo.admin.ch, data.geo.admin.ch)
  └── WebSocket /ws/v1 ─────────►  Agent backend (backend/)
                                     ├─ Amazon Bedrock - Claude / Mistral, EU regions
                                     ├─ MCP client ──► geodata MCP server (geosearch/)
                                     │                 10 intent-oriented Swiss geodata tools
                                     └─ DynamoDB - feedback + conversation turns
```

The full design — stack decisions, services, the Swisstopo connector and the API limits it
honors, security notes, and the manual demo script — is in
[`docs/architecture.md`](docs/architecture.md). The chat/agent contract is in
[`docs/protocol.md`](docs/protocol.md) with JSON Schemas under [`docs/protocol/`](docs/protocol/).
The agent backend's design - the MCP client, the LLM loop, and the AWS deployment (ECS
Fargate + ALB) - is in [`docs/architecture.md`](docs/architecture.md#backend-architecture)
and [`docs/deployment.md`](docs/deployment.md#backend-deployment); model choice and the
current Bedrock access situation are in [`docs/llm.md`](docs/llm.md); the evaluation set and
model benchmark are in [`docs/evals.md`](docs/evals.md).

## MCP tools

The production [`geosearch`](geosearch/README.md) server exposes ten intent-oriented tools.
The model chooses and chains them; users ask ordinary questions rather than selecting tools.

| Tool | Purpose |
| --- | --- |
| `search_layers` | Discover official Swiss datasets by subject and return actionable official-layer references. |
| `geocode_location` | Resolve addresses, parcels, postcodes, and named points in WGS84 and LV95. |
| `describe_layer` | Inspect layer metadata, schema, attributes, services, legend, timestamps, and downloads. |
| `identify_at_point` | Retrieve complete feature properties and official links at an exact location. |
| `search_locations` | Resolve cantons, districts, communes, localities, and Switzerland to administrative areas. |
| `display_division` | Prepare an administrative boundary as a personalized GeoParquet layer. |
| `filter_features` | Fetch all matching features inside a real boundary or current map bbox using validated filters. |
| `display_catalog_layer` | Offer an official WMS, WMTS, or GeoJSON layer for the user to add to the map. |
| `analyze_features` | Calculate counts, measurements, extents, groups, top values, and numeric statistics. |
| `display_layer` | Publish a fetched, geocoded, or identified result as a personalized GeoParquet layer. |

There are deliberately two map outputs:

- **Official map layer** — existing nationwide geo.admin.ch content; click its exact title in
  chat, then choose **Add map layer**, **Remove map layer**, or **Layer details**.
- **Personalized result layer** — the exact point, parcel, boundary, or filtered features made
  for the question; use **Show result on map** on its result card.

Complete input/output contracts and acceptance cases are in
[`docs/mcp-tool-catalog.md`](docs/mcp-tool-catalog.md). The latest sequential local
browser/agent/MCP acceptance run is recorded in
[`docs/local-e2e-acceptance-report-2026-08-18.md`](docs/local-e2e-acceptance-report-2026-08-18.md).

### Example questions

```text
What official Swiss datasets are available about avalanche hazards?

Find the exact coordinates of Seftigenstrasse 264, 3084 Wabern.
Show me on the map.

Locate Seftigenstrasse 264, 3084 Wabern; return the EGRID, official PDF
extract, online extract, and responsible authority. Prepare the exact parcel
result for the map and offer the official nationwide ÖREB availability layer separately.

Find every municipality in canton Zug. Tell me the exact count, total area,
total boundary length, minimum/maximum/average municipality area, and show both
the municipalities and canton boundary on the map.

Show me flood hazards in Valais.
```

## Repository layout

```text
frontend/      Lit + TypeScript + Vite chat + map application
backend/       Python agent backend: protocol v1, Bedrock LLM loop, MCP client, persistence
geosearch/     Production MCP: ten Swiss geodata discovery, query, analysis, and map tools
mcp_dummy/     Six-tool compatibility stand-in backed by the real geo.admin.ch APIs
evals/         Question set + runner; doubles as a side-by-side model benchmark
mock-agent/    Node WebSocket server implementing the agent protocol for development
layers/        Per-layer presentation overrides (layers_wmts.json5)
infra/         CloudFormation templates for the backend stacks
docs/          Architecture, the agent WebSocket protocol (+ JSON Schemas), LLM, deployment, evals
scripts/       Operational helpers (deploy-frontend.sh, deploy-backend.sh, deploy-backend-stack.sh, ask-llm.py, read-db.sh)
```

## Getting started

```bash
git clone https://github.com/swisstopo/sgs-llm.git
cd sgs-llm
```

### Run the geodata MCP server (terminal 1)

Build the index once - it fetches the catalogue and the boundary polygons and embeds them
through Bedrock, so it needs credentials and about twelve minutes. Everything it writes
lands in the gitignored `index/`, and the server only reads it:

```bash
python -m venv geosearch/.venv
geosearch/.venv/bin/pip install -r geosearch/requirements-dev.txt
export AWS_BEARER_TOKEN_BEDROCK=<key>
geosearch/.venv/bin/python -m geosearch.build     # once, ~12 min
geosearch/.venv/bin/python -m geosearch.server    # http://127.0.0.1:8790/mcp
```

With no `GEOSEARCH_S3_BUCKET` set it boots an in-process moto on a free port and publishes
answer layers there, so the browser fetches them over ordinary presigned URLs and no AWS
bucket is involved.

> The rerank stage resolves its region as `BEDROCK_SECONDARY_REGION` → `BEDROCK_REGION` →
> `eu-west-1`. Ministral is **not** offered in `eu-central-1`, so exporting only
> `BEDROCK_REGION=eu-central-1` in a shell shared with the backend silently degrades every
> search to unfiltered vector hits. Export `BEDROCK_SECONDARY_REGION=eu-west-1` too.

`python -m mcp_dummy.server` (port 8788) is the compatibility alternative: no index, no
build, and only six tools. Integration tests and the compatibility evaluation categories
use it; production-tool evaluations use a running `geosearch` server.

### Run an agent backend (terminal 2)

Either the real backend, which answers with a live model and real geodata (needs a Bedrock
key and the project VPN - see
[`docs/deployment.md`](docs/deployment.md#run-the-backend-locally)):

```bash
cd backend
python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
export AWS_BEARER_TOKEN_BEDROCK=<key>
export BEDROCK_PRIMARY_MODEL_ID=eu.anthropic.claude-sonnet-4-6
export BEDROCK_SECONDARY_MODEL_ID=mistral.ministral-3-14b-instruct
export BEDROCK_SECONDARY_REGION=eu-west-1
export MCP_SERVER_URL=http://127.0.0.1:8790/mcp   # 8788 for mcp_dummy
PYTHONPATH=..:. .venv/bin/python -m uvicorn app.main:app --port 8787 --reload
```

…or the mock agent, which needs nothing and replays canned scenarios:

```bash
cd mock-agent
npm install
npm start          # WebSocket on ws://localhost:8787/ws/v1, feedback on /feedback
```

Both serve the same endpoints on the same port, so the frontend does not care which is
running.

### Run the frontend (terminal 3)

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

The agent WebSocket URL and feedback endpoint are configured at runtime in
`frontend/public/config.json` (no rebuild needed to repoint them in a deployment).

Open the Chat panel and try any question under [Example questions](#example-questions).
When an answer names an official layer, click its title to inspect or add it. When an answer
produces a personalized result card, click **Show result on map** instead.

### Other frontend commands

```bash
npm run build         # type-check and produce a production build in dist/
npm test              # unit tests (vitest)
npm run lint          # eslint
npm run format:check  # prettier (CI enforces this; npm run format fixes)
npm run typecheck     # tsc --noEmit
```

CI (GitHub Actions) runs lint, the format check, the tests, and the build on
every push and pull request; pushes to `main` additionally trigger the
automatic deployment described below.

### Docker

A production image (static build served by nginx, with SPA fallback) is built from the
repository root so the `layers/` catalog is available to the build:

```bash
docker build -f frontend/Dockerfile -t sgs-llm-frontend .
docker run -p 8080:80 sgs-llm-frontend
```

## Deployment

A POC is deployed on AWS at **https://denpw8uo5zpkl.cloudfront.net/** — the static
frontend is on **S3 + CloudFront**; `/ws/v1`, `/feedback`, and `/data/*` route through an
**ALB** to the agent backend on **ECS Fargate**. The public exploration MCP is mounted at
`/mcp` in that same backend process. The backend reaches the separate private geosearch
MCP service through ECS Service Connect.

```text
                 ┌────────────── CloudFront (HTTPS / wss) ──────────────┐
 browser ──────► │  /                           → S3 (private, OAC)       │
                 │  /ws/v1, /feedback, /data/*                         │
                 │  /mcp                       → ALB → agent + MCP       │
                 └───────────────────────────────────────────────────────┘
                                                       │ Service Connect
                                                       ▼
                                                geosearch MCP (Fargate)
```

**Every push to `main` redeploys the frontend automatically**: the `deploy` job
in the CI workflow assumes a scoped IAM role via GitHub OIDC (no stored AWS
keys) and runs the deploy script after the checks pass.

The full process — reproduce-from-scratch steps, the
[`frontend`](scripts/deploy-frontend.sh), [`backend`](scripts/deploy-backend.sh), and
[`geosearch`](scripts/deploy-geosearch.sh) redeploy scripts, the OIDC role,
the retained EC2 rollback origin, cost/teardown, and the CloudFront configuration — is in
[`docs/deployment.md`](docs/deployment.md). Manual frontend redeploy fallback:

```bash
PROFILE=swisstopo ./scripts/deploy-frontend.sh
```

The **agent backend** runs as a container on **ECS Fargate behind an ALB** (image from
**ECR**, same CloudFront distribution, same GitHub-OIDC deploy pattern), with Bedrock for
inference and DynamoDB for feedback and conversation logs. Its infrastructure is defined in
[`infra/`](infra/) as two CloudFormation stacks and is deployed and operable today. Both the
deploy workflow and `scripts/deploy-backend.sh` build `backend/Dockerfile` whenever it is
present, so committing it is what puts the real backend in production; `mock-agent/` stays
available as the rollback image. Deploy, environment contract, runbook and teardown are in
[`docs/deployment.md`](docs/deployment.md#backend-deployment). Manual redeploy fallback:

```bash
PROFILE=swisstopo ./scripts/deploy-backend.sh
```

## Support

Use the established Swisstopo SGS LLM project channels for support and coordination.

## Authors & acknowledgements

This project is developed for Swisstopo with contributions from:

- [Ageospatial Sàrl](https://www.ageospatial.com) - frontend, web map, Swisstopo API
  connectors, and MCP-compatible connector design
- [askEarth AG](https://ask.earth) - LLM provisioning, agent integration, MCP client
  integration, and testing framework

The work is financed in the context of the Swiss Geoinformation Strategy (SGS).

## License

See [LICENSE](LICENSE).

## Related projects

- [`swisstopo/sgs-llm-module`](https://github.com/swisstopo/sgs-llm-module) -
  companion module repository for the SGS LLM prototype.
