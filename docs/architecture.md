# Architecture

## Overview

The SGS LLM prototype is a chat + web map application for Swiss federal
geodata. This phase implements the **frontend work package**; the agent
backend (LLM orchestration, MCP client) is developed separately and connects
over the WebSocket protocol described in [protocol.md](./protocol.md).

```text
┌─────────────────────────────────────────────────────────────┐
│ Frontend (this repo, frontend/)                             │
│   Lit 3 + TypeScript + Vite                                 │
│   OpenLayers map · @swissgeol/ui-core design system         │
│                                                             │
│   ├── direct Swisstopo API calls (catalog, identify,        │
│   │   legends, layersConfig, WMTS tiles)                    │
│   └── WebSocket /ws/v1 ──► Agent backend (askEarth, later)  │
│                            └─ mock-agent/ in development    │
└─────────────────────────────────────────────────────────────┘
```

Two tracks make the app dynamic before the agent backend exists:

- **Track A — direct Swisstopo interactivity.** Browse the official catalog
  tree (CatalogServer) with a client-side filter, add WMTS overlays,
  identify-on-click (MapServer identify), and legends, all against the public
  `api3.geo.admin.ch` / `wmts.geo.admin.ch` services.
- **Track B — chat against the protocol.** The chat panel speaks protocol
  v1 to a configurable WebSocket endpoint. The bundled `mock-agent/` is the
  executable reference implementation, streaming progress events, markdown
  answers, and data layers.

## Stack decisions

| Decision | Rationale |
| --- | --- |
| Lit 3 web components | Consistency with swissgeol-viewer-suite (the swissgeol.ch flagship); first-class fit with the shared design system |
| OpenLayers | The 2D engine proven in swissgeol-assets-suite with Swisstopo services |
| @swissgeol/ui-core | Provides the SwissGeo family's Inter font and design-system conventions. Our palette is defined as `--sgc-*` tokens in `frontend/src/style/theme.css` (single source of truth; components reference the vars without per-rule fallbacks) |
| RxJS services + @lit/context | Service classes own state as `BehaviorSubject`s, provided via context; `ObservableController` bridges emissions into Lit re-renders |
| SwissGeo-style shell | Left icon rail (chat, displayed maps, geocatalog, feedback, about) opening one flyout panel at a time; language selector at the rail bottom — mirrors viewer.swissgeo |
| Official geocatalog | Topic list + per-topic catalog tree from the Swisstopo CatalogServer API (cached per topic and language); per-layer presentation overrides in `layers/layers_wmts.json5` |
| i18next, German fallback | de/fr/it/en; the active language is passed to every Swisstopo API call and WS message |
| marked + DOMPurify | Agent markdown is sanitized; API HTML (htmlPopup, legends) renders only in sandboxed iframes |

## Light DOM exceptions

`<sgs-app>` and `<sgs-map>` render in light DOM because `ol/ol.css` is a
document-level stylesheet that cannot style inside shadow roots (map
controls, attribution, overlay positioning). Their layout styles live in
`frontend/src/style/global.css`. Everything else uses shadow DOM; ui-core
custom properties inherit through.

## Services

| Service | Responsibility |
| --- | --- |
| `MapService` | Owns the single `ol/Map`: view, basemaps (WMTS from layersConfig), camera (fitBBox), click stream, identify highlight layer |
| `LayerService` | Active layers (official WMTS overlays + chat data layers): add/remove, visibility, opacity, order (z-index), zoom-to |
| `CatalogService` | layersConfig cache per language, geocatalog topics/trees (CatalogServer) |
| `UiService` | Shell state: which rail flyout panel is open |
| `ChatService` | Chat state machine over `AgentClient` events (progress steps, markdown, layers, errors, cancel) |
| `AgentClient` | WebSocket lifecycle: exponential-backoff reconnect, frame parsing with forward-compatible guards |

## Data layers from chat

`LayerSpec.format` currently supports `geojson` end-to-end. `parquet`
(GeoParquet via presigned URLs, as planned for the production agent) is
stable in the protocol but renders as a "format not yet supported" notice.
Follow-up path: `parquet-wasm` → Arrow → GeoJSON features into the same
`VectorSource` behind `LayerService.addDataLayer`'s format switch — no
protocol change required.

## Swisstopo connector

All Swisstopo access lives in `frontend/src/swisstopo/` — thin, typed
wrappers over the public geo.admin.ch APIs
([docs.geo.admin.ch](https://docs.geo.admin.ch/)), sharing one HTTP helper
(`http.ts`: 15 s timeout + caller `AbortSignal`). No offline preprocessing;
everything is queried live and cached in memory.

| Endpoint | Module | Limits honored |
| --- | --- | --- |
| `{topic}/CatalogServer` + topics | `catalogApi.ts` | promise-cached per topic + language; non-`prod` staging entries dropped |
| `MapServer/identify` | `identifyApi.ts` | `limit=200` (API max; default 50, applied per underlying table); `geometryFormat=geojson` (avoids ESRI-JSON conversion); superseded clicks aborted |
| `MapServer/layersConfig` | `layersConfigApi.ts` | ~1 MB per language, promise-cached per language with retry-on-failure |
| `MapServer/{layer}/legend`, htmlPopup | `legendApi.ts`, `identifyApi.ts` | untrusted HTML, sandboxed iframes only |
| `wmts.geo.admin.ch` XYZ tiles | `wmts.ts` | format/timestamp always resolved from layersConfig |

**Deliberately not used by the frontend** (bulk-data concerns owned by the
future MCP server's `fetch_layer_data`, per the project design): the
`SearchServer` (location / layer / feature search — the geocatalog browses
the CatalogServer tree and filters it client-side instead), identify
`offset` paging, grid splitting + cross-cell deduplication, rate limiting of
fan-out requests, the STAC download API, and `layerDefs` attribute filtering
(supported on 11 queryable layers only). A click identify (point + pixel
tolerance feeding a popup) never needs more than one page, and identify has
no order parameter.

## Runtime configuration

Vite environment variables are build-time; the agent WebSocket URL and the
feedback endpoint must be deploy-time. The app loads `/config.json` at
startup (`frontend/public/config.json` → `{ agentWsUrl, feedbackUrl }`,
served with `Cache-Control: no-store` by the bundled nginx config) — replace
it in the deployment to point at the real agent backend and feedback
service. All Swisstopo API base URLs live in `frontend/src/config.ts` so a
proxy can be slotted in if needed (the public APIs allow cross-origin
requests today, but that is operational behavior, not a contract).

## Security notes

- Agent markdown: sanitized with DOMPurify (no raw HTML, safe link targets).
- Swisstopo htmlPopup and legend fragments: untrusted HTML, rendered
  exclusively inside `sandbox=""` iframes.
- No authentication, no user data storage (public prototype, by design).

## Testing

`vitest` (node environment) covers the logic surface: protocol guards,
AgentClient state machine, ChatService reducer, catalog parsing/merging,
style mapping, API wrappers with mocked fetch. The markdown renderer runs
under jsdom (DOMPurify needs a DOM). Lit component DOM tests are
deliberately out of scope for the POC: ui-core's Stencil elements need a
real browser registry; the upgrade path is vitest browser mode +
`@open-wc/testing`.

## Demo script (manual verification)

1. `cd mock-agent && npm start` and `cd frontend && npm run dev`
2. Rail → Chat: ask "Zeige mir Hochwasser im Wallis" → progress steps
   stream → markdown answer + layer card → "Auf Karte anzeigen" →
   polygons render, map zooms
3. Rail → Geocatalog: pick a topic, filter, add a layer ([+]); click it
   again to remove it from the map
4. Rail → Displayed maps: switch Color/Grey/Aerial via the eye toggles;
   adjust layer opacity; open a legend
5. Click a feature of an identify-capable layer → popup with LV95 readout
6. Rail → Feedback: submit (entry lands in mock-agent/feedback.log)
7. Rail → About: project info panel
8. Switch the language via the rail's translate icon → labels re-localize
9. Send a message containing `/error`, then one with `/slow` + cancel
10. Kill and restart the mock agent → connection badge recovers
