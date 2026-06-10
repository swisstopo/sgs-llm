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

This repository currently contains the **frontend work package**: a runnable chat + web map
application (`frontend/`) plus a small **mock agent** (`mock-agent/`) that stands in for the
LLM agent backend during development. The frontend talks to the public Swisstopo APIs
directly for map interactivity, and to the agent backend over a versioned WebSocket protocol
([`docs/protocol.md`](docs/protocol.md)).

The production agent backend (LLM provisioning, orchestration, MCP client) is developed
separately and connects over the same protocol. This is a prototype — not for operational
use; interfaces and layout may still change.

A live POC instance (frontend + mock-agent) is deployed on AWS at
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
    answers, and data layers rendered on the map; a "+" button starts a new conversation
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
  └── WebSocket /ws/v1 ─────────►  Agent backend (askEarth, separate)
                                   └─ mock-agent/ during development
```

The full design — stack decisions, services, the Swisstopo connector and the API limits it
honors, security notes, and the manual demo script — is in
[`docs/architecture.md`](docs/architecture.md). The chat/agent contract is in
[`docs/protocol.md`](docs/protocol.md) with JSON Schemas under [`docs/protocol/`](docs/protocol/).

## Repository layout

```text
frontend/      Lit + TypeScript + Vite chat + map application
mock-agent/    Node WebSocket server implementing the agent protocol for development
layers/        Per-layer presentation overrides (layers_wmts.json5)
docs/          Architecture, the agent WebSocket protocol (+ JSON Schemas), and deployment
scripts/       Operational helpers (e.g. deploy-frontend.sh)
```

## Getting started

```bash
git clone https://github.com/swisstopo/sgs-llm.git
cd sgs-llm
```

### Run the mock agent (terminal 1)

```bash
cd mock-agent
npm install
npm start          # WebSocket on ws://localhost:8787/ws/v1, feedback on /feedback
```

### Run the frontend (terminal 2)

```bash
cd frontend
npm install
npm run dev        # http://localhost:5173
```

The agent WebSocket URL and feedback endpoint are configured at runtime in
`frontend/public/config.json` (no rebuild needed to repoint them in a deployment).

### Other frontend commands

```bash
npm run build       # type-check and produce a production build in dist/
npm test            # unit tests (vitest)
npm run lint        # eslint
npm run typecheck   # tsc --noEmit
```

### Docker

A production image (static build served by nginx, with SPA fallback) is built from the
repository root so the `layers/` catalog is available to the build:

```bash
docker build -f frontend/Dockerfile -t sgs-llm-frontend .
docker run -p 8080:80 sgs-llm-frontend
```

## Deployment

A POC is deployed on AWS at **https://denpw8uo5zpkl.cloudfront.net/** — the static
frontend on **S3 + CloudFront**, with the development **mock-agent** on a single
**EC2** instance behind the same CloudFront distribution (so the site, the chat
`wss://` WebSocket, `/feedback`, and `/data/*` are all served from one HTTPS
origin).

```text
                 ┌──────────── CloudFront (HTTPS / wss) ───────────┐
 browser ──────► │  /                         → S3  (private, OAC)  │
                 │  /ws/v1, /feedback, /data/* → EC2 (mock-agent)    │
                 └──────────────────────────────────────────────────┘
```

The full process — reproduce-from-scratch steps, the redeploy script
([`scripts/deploy-frontend.sh`](scripts/deploy-frontend.sh)), how to operate the
EC2 mock-agent, cost/teardown, and the CloudFront configuration — is in
[`docs/deployment.md`](docs/deployment.md). Redeploy the frontend with:

```bash
PROFILE=swisstopo ./scripts/deploy-frontend.sh
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
