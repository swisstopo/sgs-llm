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

## Features

- **SwissGeo-style shell** — a left icon rail opening one flyout panel at a time:
  - **Search** — locations (geocoding, fly-to) and the full layer catalog (SearchServer)
  - **Displayed maps** — three Swisstopo basemaps (color / grey / aerial) and the active
    layer list with visibility, opacity, ordering, zoom-to, and legends
  - **Geocatalog** — the official Swisstopo catalog tree (CatalogServer): topic selector,
    in-tree search, add/remove layers
  - **Chat** — natural-language conversation with streamed tool-progress, sanitized markdown
    answers, and data layers rendered on the map
  - **Feedback** — a feedback form posted to a configurable endpoint
  - **About** — project, partners, and data-source information
- **Identify on click** — feature attributes from the MapServer identify endpoint, with an
  LV95 coordinate readout
- **Multilingual** — German, French, Italian, English; the active language is passed to every
  Swisstopo API call and chat message
- **Lean live connectors** — thin, typed wrappers over the public geo.admin.ch APIs with
  request timeouts, cancellation of superseded requests, and the API's paging/word limits
  respected (see [`docs/architecture.md`](docs/architecture.md))

## Architecture overview

```text
Browser (frontend/, Lit + OpenLayers + @swissgeol/ui-core)
  ├── direct calls ─────────────►  Swisstopo public APIs
  │                                (api3.geo.admin.ch, wmts.geo.admin.ch)
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
docs/          Architecture and the agent WebSocket protocol (+ JSON Schemas)
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
