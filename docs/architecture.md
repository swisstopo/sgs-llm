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
│   ├── direct Swisstopo API calls (search, identify,         │
│   │   legends, layersConfig, WMTS tiles)                    │
│   └── WebSocket /ws/v1 ──► Agent backend (askEarth, later)  │
│                            └─ mock-agent/ in development    │
└─────────────────────────────────────────────────────────────┘
```

Two tracks make the app dynamic before the agent backend exists:

- **Track A — direct Swisstopo interactivity.** Layer catalog search and
  geocoding (SearchServer), official WMTS overlays, identify-on-click
  (MapServer identify), and legends, all against the public
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
| @swissgeol/ui-core | The SwissGeo design system (Stencil web components, `--sgc-*` CSS variables, Inter font); brand override in `frontend/src/style/theme.css` |
| RxJS services + @lit/context | Service classes own state as `BehaviorSubject`s, provided via context; `ObservableController` bridges emissions into Lit re-renders |
| JSON5 layer catalog (`layers/`) | Declarative curated layer tree, pattern adapted from swissgeol-viewer-suite; layer metadata always resolved at runtime from layersConfig |
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
| `MapService` | Owns the single `ol/Map`: view, basemaps (WMTS from layersConfig), camera (flyTo/fitBBox), click stream, identify highlight layer |
| `LayerService` | Active layers (official WMTS overlays + chat data layers): add/remove, visibility, opacity, order (z-index), zoom-to |
| `CatalogService` | layersConfig cache per language, curated-tree hydration, layer/location search |
| `ChatService` | Chat state machine over `AgentClient` events (progress steps, markdown, layers, errors, cancel) |
| `AgentClient` | WebSocket lifecycle: exponential-backoff reconnect, frame parsing with forward-compatible guards |

## Data layers from chat

`LayerSpec.format` currently supports `geojson` end-to-end. `parquet`
(GeoParquet via presigned URLs, as planned for the production agent) is
stable in the protocol but renders as a "format not yet supported" notice.
Follow-up path: `parquet-wasm` → Arrow → GeoJSON features into the same
`VectorSource` behind `LayerService.addDataLayer`'s format switch — no
protocol change required.

## Runtime configuration

Vite environment variables are build-time; the agent WebSocket URL must be
deploy-time. The app loads `/config.json` at startup
(`frontend/public/config.json`, served with `Cache-Control: no-store` by
the bundled nginx config) — replace it in the deployment to point at the
real agent backend. All Swisstopo API base URLs live in
`frontend/src/config.ts` so a proxy can be slotted in if needed (the public
APIs allow cross-origin requests today, but that is operational behavior,
not a contract).

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
2. Browse the catalog tab → add a layer → adjust opacity
3. Search "wald" → add a layer; search "Bern" → fly-to
4. Ask "Zeige mir Hochwasser im Wallis" → progress steps stream → markdown
   answer + layer card → "Auf Karte anzeigen" → polygons render, map zooms
5. Click a transit stop with the öV-Haltestellen layer active → identify
   popup with LV95 readout → expand a feature
6. Open a layer legend from the layers tab
7. Switch the language to FR → repeat any step; layer labels re-localize
8. Send a message containing `/error`, then one with `/slow` + cancel
9. Kill and restart the mock agent → connection badge recovers
