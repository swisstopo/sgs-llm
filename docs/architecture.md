# Architecture

## System diagram

The whole system in one picture. The browser runs the frontend, served via
**CloudFront** from **S3**, and works two ways at once: **[Track A](#overview)**
calls the Swisstopo public APIs directly for the catalog, tiles, and identify;
**[Track B](#overview)** speaks WebSocket protocol v1 through CloudFront and an
**ALB** to the agent backend on **ECS Fargate**. The backend runs the LLM loop
on **Amazon Bedrock** and calls the geodata **MCP server**, which produces the
result **data layers** in S3; the backend relays their presigned URLs to the
browser, which fetches them. The backend also persists submitted **feedback** and
**chat turns** to DynamoDB. Until swisstopo's MCP server exists there is no
geodata source to answer from, so the chat **refuses every turn** and waits for
`MCP_SERVER_URL` (see
[`protocol.md`](./protocol.md#waiting-for-the-production-mcp-server)); the map is
unaffected.

```mermaid
flowchart TB
    browser["`**Browser** · frontend/
————
Lit · OpenLayers (EPSG:2056) · chat + map`"]

    topo["`**Swisstopo public APIs** · geo.admin.ch
————
WMTS · WMS · catalog / identify / GeoJSON`"]

    cf["`**CloudFront**
————
HTTPS / wss · single origin`"]
    s3f[("`**S3** · static frontend
————
built assets + config.json`")]
    alb["`**ALB**
————
WebSocket upgrade`"]
    orch["`**Agent backend** · ECS Fargate
————
backend/ · WS protocol v1 · LLM loop · MCP client`"]
    bedrock["`**Amazon Bedrock**
————
Claude Sonnet · Mistral · EU profiles`"]
    mcp["`**MCP server(s)**
————
geodata tools · swisstopo's
required for the chat to answer`"]
    s3d[("`**S3** · data-layer artifacts
————
GeoJSON / GeoParquet`")]
    ddb[("`**DynamoDB**
————
feedback · conversation turns (TTL)`")]

    browser -- "https / wss" --> cf
    cf -- "default →" --> s3f
    cf -- "/ws/v1 · /feedback · /data/* →" --> alb
    alb -- "WebSocket" --> orch
    browser -- "Track A · direct calls" --> topo
    orch -- "LLM · InvokeModel" --> bedrock
    orch -- "MCP client" --> mcp
    orch -- "feedback · chat log" --> ddb
    mcp -- "produces data layers" --> s3d
    mcp -. "tool JSON (+ layer URLs)" .-> orch
    orch -. "answer + layer URLs" .-> browser
    s3d -. "presigned URLs · fetched by browser" .-> browser
    mcp -. "bulk geodata (fetch_layer_data)" .-> topo
```

## Overview

The SGS LLM prototype is a chat + web map application for Swiss federal
geodata. The frontend and the agent backend both live in this repository and
meet at the WebSocket protocol described in [protocol.md](./protocol.md); the
frontend additionally calls the Swisstopo APIs directly for map interactivity.

```text
┌─────────────────────────────────────────────────────────────┐
│ Frontend (this repo, frontend/)                             │
│   Lit 3 + TypeScript + Vite                                 │
│   OpenLayers map (EPSG:2056) · @swissgeol/ui-core           │
│                                                             │
│   ├── direct Swisstopo API calls (catalog, identify,        │
│   │   legends, layersConfig, WMTS/WMS tiles, GeoJSON)       │
│   └── WebSocket /ws/v1 ──► Agent backend (backend/)         │
│                            └─ mock-agent/ as a test double  │
└─────────────────────────────────────────────────────────────┘
```

Two tracks serve the app, and they are independent - the map stays fully usable
if the agent is unavailable:

- **Track A — direct Swisstopo interactivity.** Browse the official catalog
  tree (CatalogServer) with a client-side filter and translated topic names,
  add any displayable catalog layer (WMTS, WMS, or GeoJSON — only genuinely
  non-displayable entries are greyed out), open per-layer information
  dialogs, identify-on-click (MapServer identify), and per-layer legends
  shown automatically in a top-right map overlay — all against the public
  `api3.geo.admin.ch` / `wmts.geo.admin.ch` / `wms.geo.admin.ch` /
  `data.geo.admin.ch` services.
- **Track B — chat against the protocol.** The chat panel speaks protocol
  v1 to a configurable WebSocket endpoint. The bundled `mock-agent/` is the
  executable reference implementation, streaming progress events, markdown
  answers, and data layers.

## Stack decisions

| Decision | Rationale |
| --- | --- |
| Lit 3 web components | Consistency with swissgeol-viewer-suite (the swissgeol.ch flagship); first-class fit with the shared design system |
| OpenLayers | The 2D engine proven in swissgeol-assets-suite with Swisstopo services |
| Swiss LV95 projection (EPSG:2056) | The map view, all sources, and identify run in the native Swiss CRS, like map.geo.admin.ch / SwissGeo. The swisstopo LV95 tile grid is a rectangle fully covered by map data, so the basemap renders cleanly (in Web Mercator the Swiss-only coverage appears as a skewed frame in a void). See "Map projection and zoom ladder" below |
| @swissgeol/ui-core | Provides the SwissGeo family's Inter font and design-system conventions. Our palette is defined as `--sgc-*` tokens in `frontend/src/style/theme.css` (single source of truth; components reference the vars without per-rule fallbacks) |
| RxJS services + @lit/context | Service classes own state as `BehaviorSubject`s, provided via context; `ObservableController` bridges emissions into Lit re-renders |
| SwissGeo-style shell | Left icon rail (chat, displayed maps, geocatalog, feedback, about) opening one flyout panel at a time, sliding in as an animated overlay over the map; the panel is drag-resizable at its right edge (width persisted in localStorage); language selector at the rail bottom — mirrors viewer.swissgeo |
| SwissGeo-style map controls | Custom bottom-right cluster (geolocation above a zoom bar) instead of the small OpenLayers default zoom control; geolocation transforms to LV95 with a Swiss-bounds check |
| Official geocatalog | Topic list (translated names, `ech` pinned first) + per-topic catalog tree from the Swisstopo CatalogServer API (cached per topic and language); per-layer presentation overrides in `layers/layers_wmts.json5` |
| i18next, German fallback | de/fr/it/en/rm; the active language is passed to every Swisstopo API call and WS message |
| marked + DOMPurify | Agent markdown and Swisstopo legend fragments are sanitized with DOMPurify (a shared hook forces sanitized links to open in a new tab with `rel="noopener noreferrer"`); the richer identify htmlPopup renders only in a sandboxed iframe |

## Map projection and zoom ladder (LV95)

The whole map pipeline runs in **EPSG:2056** (registered via proj4 at
startup, `frontend/src/lib/projection.ts`). `frontend/src/map/swissGrid.ts`
holds the swisstopo LV95 tile grid (origin `[2420000, 1350000]`, extent
`[2420000, 1030000, 2900000, 1350000]`, 29 resolutions from the official
WMTS capabilities) shared by all WMTS sources, plus the view's zoom ladder.

The view snaps to the official ladder (650 → 0.25 m/px,
`constrainResolution`), so tiles always render 1:1 at a real swisstopo zoom
level — the zoomed-out levels carry the light generalized national-map style
(with the neighboring countries), the deeper levels the detailed styles.
The view's extent constraint is center-only: users can zoom out far enough
to see the whole tile grid, but cannot pan the center off it. Everything
that crosses a projection boundary is explicit: agent bboxes are WGS84 and
transformed at the `MapService` camera methods; chat/official GeoJSON is
reprojected on read (official files declare their CRS, usually EPSG:2056);
identify runs with `sr=2056`; the coordinate readout is the map coordinate.

## Light DOM exceptions

`<sgs-app>` and `<sgs-map>` render in light DOM because `ol/ol.css` is a
document-level stylesheet that cannot style inside shadow roots (map
controls, attribution, overlay positioning). Their layout styles live in
`frontend/src/style/global.css`. Everything else uses shadow DOM; ui-core
custom properties inherit through.

## Services

| Service | Responsibility |
| --- | --- |
| `MapService` | Owns the single `ol/Map`: LV95 view on the official zoom ladder, basemaps (WMTS from layersConfig), camera (fitBBox / fitLV95Extent / zoomBy), click stream, identify highlight layer, geolocation marker |
| `LayerService` | Active layers (official WMTS/WMS/GeoJSON overlays + chat data layers): add/remove, visibility, opacity, order (buttons and drag-and-drop via `moveLayerToIndex`), zoom-to (data-layer bbox or vector source extent), periodic refresh of live GeoJSON layers |
| `CatalogService` | layersConfig cache per language, geocatalog topics/trees (CatalogServer) |
| `UiService` | Shell state: which rail flyout panel is open; the layer-info dialog request |
| `ChatService` | Chat state machine over `AgentClient` events (progress steps, markdown, layers, errors, cancel) |
| `AgentClient` | WebSocket lifecycle: exponential-backoff reconnect, frame parsing with forward-compatible guards |

## Data layers from chat

`LayerSpec.format` currently supports `geojson` end-to-end. `parquet`
(GeoParquet via presigned URLs, as planned for the production agent) is
stable in the protocol but renders as a "format not yet supported" notice.
Follow-up path: `parquet-wasm` → Arrow → GeoJSON features into the same
`VectorSource` behind `LayerService.addDataLayer`'s format switch — no
protocol change required.

## Backend architecture

The chat side is served by the agent backend, which lives in this repository under
[`backend/`](../backend/) and connects over the WebSocket protocol. It is **implemented**:
a Python service (FastAPI + uvicorn) running the LLM loop on Bedrock through the Converse
API, an MCP client for the geodata tools, and persistence for feedback and conversation
turns. How the service is deployed is in
[`deployment.md`](./deployment.md#backend-deployment); the client side of the geodata tool
interface is in [MCP client interface](#mcp-client-interface); model choice is in
[`llm.md`](./llm.md).

```text
┌──────────────────────────────────────────────────────────────────┐
│ Agent backend (backend/, this repository)                          │
│   Dockerized service · WebSocket protocol v1 (stateless)           │
│   ECS Fargate, 4 vCPU / 8 GB behind an ALB                         │
│                                                                    │
│   /ws/v1 ◄──► agent orchestrator (LLM loop)                        │
│                 ├─ LLM ──► Amazon Bedrock — Claude + Mistral        │
│                 │          (eu.* EU inference profiles)            │
│                 └─ MCP client ──► MCP server(s): geodata tools,    │
│                                   fetch_layer_data  (separate)     │
│                                                                    │
│   /feedback  ──► DynamoDB  sgs-llm-feedback       (TTL)            │
│   chat turns ──► DynamoDB  sgs-llm-conversations  (TTL)            │
│   data layers ──► GeoJSON / GeoParquet on S3 (presigned URLs)      │
└──────────────────────────────────────────────────────────────────┘
```

- **Stateless protocol v1** — the backend receives the full conversation history and map context on every turn (see [protocol.md](./protocol.md)), so it can restart or scale freely; versioning at the URL (`/ws/v1`) lets it release independently of the frontend.
- **MCP client + LLM orchestrator** — the backend runs the LLM loop and the MCP client that calls the geodata tools; the MCP **server** is a separate component (see [Swisstopo connector](#swisstopo-connector)).
- **Amazon Bedrock, Claude via the EU inference profile** (`eu.anthropic.claude-*`) — managed, IAM-authenticated model access that stays within EU regions, with no API key to store; model choice in [`llm.md`](./llm.md).
- **Both models are first-class, in two regions.** One Converse code path serves either; they differ only in id and region, because Claude is reached through an EU inference profile in `BEDROCK_REGION` while the pilot's Mistral is offered in-region in `eu-west-1` only. Claude is tried first. An `AccessDeniedException` - which is the *expected* result until organization SCP `p-ddxnpgbm` is amended - is logged once, the model is marked unavailable for the process lifetime, and the secondary serves the turn. Claude starts working on the next task start, with no code, image or template change.
- **Prompts are per-model, and follow the model that actually served the turn.** `MODEL_PROMPTS` in [`app/agent/prompts.py`](../backend/app/agent/prompts.py) maps a case-insensitive substring of the Bedrock model id (`"claude"`, `"mistral"`, or a full id) to a prompt template; anything unmatched gets the shared `_BASE`. The prompt is a *callable* rendered per Converse attempt rather than once per turn, because otherwise a turn that fell back to the secondary would have been sent the primary's prompt. It is empty by default - the two pilot models currently share one prompt, and a variant should be justified by an eval run rather than a guess. Note that this makes [`evals.md`](./evals.md) a comparison of *model + prompt* pairs, which is the right thing to compare when choosing one, but state it that way when quoting a result.
- **Agent loop → protocol events** - tool and LLM progress stream as `intermediate`, the answer and data layers as `final`, turn completion as `done`, and a client `cancel` aborts the in-flight turn. The transport (`app/ws.py`) owns the exchange lifecycle and emits the terminating `done` for every outcome, so the loop cannot produce two terminal events. The final tool-loop iteration steers the model to answer with an instruction rather than by withdrawing the tool set - once a conversation contains `toolUse`/`toolResult` blocks, Bedrock rejects the whole request with `ValidationException` if no `toolConfig` accompanies them, so withdrawing them failed exactly the multi-step questions the loop exists for.
- **Degrade rather than drop.** An unreachable MCP server, a failed tool call, or an unavailable DynamoDB table never ends the exchange: the model is told the tools are unavailable, a failed tool is reported as a failed step it can work around, and a storage failure is logged and swallowed. A chat that explains what it could not reach beats a chat that disconnects.
- **But refuse rather than substitute.** Degrading applies to a geodata server that is *configured and failing*. A server that was never configured is not a degraded state, it is an unfinished deployment, and answering from the bundled stand-in would pass non-production data off as production output - so those turns are refused instead. See [Waiting for the production MCP server](./protocol.md#waiting-for-the-production-mcp-server).
- **Data layers on S3** - results are written as GeoJSON and returned as presigned URLs in `LayerSpec` (see [Data layers from chat](#data-layers-from-chat)). With no bucket configured - local development, and CI's credential-free smoke test - artifacts are held in memory and served from `/data/<name>`, the same path CloudFront already routes, so the frontend needs no special case.
- **Limits instead of a key** - the endpoint is unauthenticated by design; per-client rate limits, an origin allowlist and payload caps are what protect it. See [Limits and the optional key](./protocol.md#limits-and-the-optional-key).

## MCP client interface

The backend is the **MCP client**; the geodata tools live on a separate MCP
**server** (the connector). The client side is **implemented** as described below.

Until swisstopo's server exists there is nothing to connect to, and the backend
**refuses chat turns rather than answering from a stand-in** - the reasoning is in
[`protocol.md`](./protocol.md#waiting-for-the-production-mcp-server). Turning the chat on
is setting `MCP_SERVER_URL`; no code or image change.

The bundled [`mcp_dummy/`](../mcp_dummy/README.md) - a real MCP server over Streamable
HTTP whose tools are backed by the live geo.admin.ch APIs - therefore serves development
and measurement only. It is **not in the deployed image** and the backend never wires it
up: `MCP_SERVER_URL` is the only way it is ever reached, so running it locally
(`python -m mcp_dummy.server`) is a deliberate act. The [evaluation harness](./evals.md)
and the integration tests construct it themselves, over the SDK's in-memory transport.

Those tests use the in-memory transport rather than a loopback HTTP listener because the
loopback version had a real failure mode: uvicorn's socket accepts connections before the
ASGI lifespan has started the MCP session manager, and requests landing in that window are
answered but never handled - so the agent silently ran with no tools, in about a third of
runs under load.

Client side:

- **Transport** - connect to the server over **Streamable HTTP** (remote MCP), not stdio: `initialize`, cache `tools/list`, invoke with `tools/call`. One session per turn, so several tool calls in one answer share one `initialize` and nothing stale has to be reconnected between turns. The catalogue is paginated to the end via `next_cursor`, and the server's `ttl_ms` bounds how long the cache survives; `cache_scope` is not consulted, since it distinguishes a shared cache from a per-user one and this is the latter. An empty catalogue is never cached, so a server that answers before it is ready does not leave the agent toolless for the life of the task.
- **In the agent loop** - the server's tools are offered to the model as its tool set; each model `tool_use` becomes a `tools/call`, and the result is fed back until the model produces the final answer. When a model emits several `tool_use` blocks at once, all their results go back in one message, which is what Bedrock requires. Tool JSON Schemas are normalised before being offered (pydantic's presentation keys are stripped - Mistral is less tolerant of unexpected schema keys than Claude).
- **Mapping to protocol v1** - the client converts tool output into the frontend's events: a fetchable GeoJSON/GeoParquet URL with a WGS84 `bbox` (and optional style hint) becomes a `LayerSpec`; tool progress streams as `intermediate`; a client `cancel` aborts the in-flight `tools/call`; failures surface as `error`. The conversion is deliberately **generic** - it recognises that shape anywhere in a tool result rather than matching the bundled server's schema, so swisstopo's server should work without code changes. Anything that would fail the frontend's `isLayerSpec` guard is dropped rather than emitted, and a `bbox` that is not plausible WGS84 (LV95 metres, say) is discarded rather than sent to move the map. **One clause is implemented differently and is not yet confirmed:** a failed *tool call* surfaces as `intermediate` with `status: "failed"` rather than as `error`, because `error` is terminal and one flaky call would otherwise end the exchange. `error` is reserved for a failed turn. See [`protocol.md`](./protocol.md#intermediate--toolwork-progress).
- **Auth & secrets** - the client presents the server's credential (bearer token from Secrets Manager as `Authorization: Bearer`); the server endpoint must be reachable from the Fargate task's egress.

Needed from the server:

- The **endpoint URL**, and confirmation of **Streamable HTTP** transport and the **auth scheme**.
- The **tool catalog** — each tool's name and JSON-Schema input/output.
- For any tool that produces a map layer, a result that yields a **fetchable GeoJSON or GeoParquet URL plus a WGS84 bounding box** (and any style hint), so the client can build a `LayerSpec` without re-hosting the data.
- **Limits** — payload sizes, rate limits, and timeout / long-running behavior.

## Swisstopo connector

All Swisstopo access lives in `frontend/src/swisstopo/` — thin, typed
wrappers over the public geo.admin.ch APIs
([docs.geo.admin.ch](https://docs.geo.admin.ch/)), sharing one HTTP helper
(`http.ts`: 15 s timeout + caller `AbortSignal`). No offline preprocessing;
everything is queried live and cached in memory.

| Endpoint | Module | Limits honored |
| --- | --- | --- |
| `{topic}/CatalogServer` + topics | `catalogApi.ts` | promise-cached per topic + language; non-`prod` staging entries dropped |
| `MapServer/identify` | `identifyApi.ts` | `sr=2056`; `limit=200` (API max; default 50, applied per underlying table); `geometryFormat=geojson` (avoids ESRI-JSON conversion); superseded clicks aborted |
| `MapServer/layersConfig` | `layersConfigApi.ts` | ~1 MB per language, promise-cached per language with retry-on-failure; carries the per-layer service parameters (WMTS format/timestamps, WMS endpoint/params, GeoJSON data/style URLs) |
| `MapServer/{layer}/legend` | `legendApi.ts` | untrusted HTML, DOMPurify-sanitized; rendered inline in the map legend overlay and as the body of the layer-info dialog |
| `MapServer/.../htmlPopup` | `identifyApi.ts` | untrusted HTML, rendered only inside a `sandbox=""` iframe |
| `wmts.geo.admin.ch` XYZ tiles | `wmts.ts` | LV95 (`/2056/`) tile template; format/timestamp always resolved from layersConfig; sources share the grid from `map/swissGrid.ts` |
| `wms.geo.admin.ch` GetMap | `wms.ts` | LAYERS/FORMAT from layersConfig; `singleTile` layers use one viewport-sized image (`ImageWMS`), tiled layers use `TileWMS` with the layer's `gutter`; CRS follows the view (EPSG:2056); TIME is not sent (server default) |
| `data.geo.admin.ch` GeoJSON + `api3` vector styles | `geojsonStyle.ts` (+ `LayerService`) | features reprojected from the file's declared CRS; the geoadmin style JSON (`unique`/`range`/`single` rules, resolution windows, markers, label templates) is parsed into an OL style function with a safe default fallback; layers with `updateDelay` re-fetch periodically while on the map |

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

- Agent markdown and Swisstopo legend fragments: untrusted HTML sanitized with
  DOMPurify (scripts/styles/iframes stripped); a shared hook
  (`markdown/purifyLinkHook.ts`) forces every sanitized anchor to
  `target="_blank" rel="noopener noreferrer"`. The sanitized legend renders
  inline in the map legend overlay and in the layer-info dialog.
- Swisstopo identify `htmlPopup`: richer untrusted HTML, rendered exclusively
  inside a `sandbox=""` iframe.
- Geolocation: browser API only, used on demand for the locate button; the
  position is never sent anywhere.
- No authentication (public prototype, by design), but the chat endpoint is rate-limited
  and origin-checked, with an optional shared key that is off by default - including why
  that key cannot be a security boundary in a browser app, and why the browser cannot
  send it as a header at all: see
  [Limits and the optional key](./protocol.md#limits-and-the-optional-key).
- **Prompt injection is treated as a data problem, not only a message problem.** Tool
  results are public-source content, so the system prompt states that data is never
  instruction, and the evaluation set attacks both routes - hostile text in the user's
  message and hostile text inside fetched feature attributes
  ([`evals.md`](./evals.md#prompt-injection-via-data)).
- The **frontend** stores nothing server-side; the **agent backend** does: chat turns and
  submitted feedback (which may include an email address the user typed) are persisted to
  DynamoDB with a TTL so the pilot can be evaluated. That is personal data - see
  [`deployment.md`](./deployment.md#what-gets-stored) for the schema, retention and
  the sign-off still outstanding.

## Testing

**Backend** - `pytest` covers the whole logic surface with no AWS and no network: the
protocol (emitted frames are validated against `docs/protocol/*.schema.json`, so the
schemas stay the single source of truth), the exchange invariant over a real WebSocket,
cancel and timeout, the rate limits and origin check, the model fallback on
`AccessDeniedException`, MCP schema conversion, `LayerSpec` extraction from malformed tool
output, the DynamoDB item shapes, and the geo.admin.ch wrappers against recorded
responses. One integration test runs the **real** MCP transport against the bundled server
with only geo.admin.ch stubbed, so tool discovery, chaining, artifact publishing and
layer extraction are exercised as they run in production. The evaluation harness's own
scoring logic is tested too ([`evals.md`](./evals.md)) - a benchmark is only quotable if
its scoring is right.

That the suite needs no credentials is deliberate: it is the same property that lets CI
smoke-test the image before allowing a deploy.

**Frontend** - `vitest` (node environment) covers the logic surface: protocol guards,
AgentClient state machine, ChatService reducer, catalog parsing/merging,
style mapping (chat style hints and the geoadmin vector-style parser),
projection helpers, layer ordering/zoom/refresh logic in `LayerService`, and
API wrappers with mocked fetch. The markdown renderer and the legend
sanitizer run under jsdom (DOMPurify needs a DOM). Lit component DOM tests are
deliberately out of scope for the POC: ui-core's Stencil elements need a
real browser registry; the upgrade path is vitest browser mode +
`@open-wc/testing`.

## Demo script (manual verification)

1. `cd mock-agent && npm start` and `cd frontend && npm run dev`
2. Initial map: all of Switzerland in the light national-map style; zoom out
   once more to see the whole LV95 frame with the neighboring countries;
   zooming in two steps switches to the detailed map style
3. Rail → Chat: ask "Zeige mir Hochwasser im Wallis" → progress steps
   stream → markdown answer + layer card → "Auf Karte anzeigen" →
   polygons render, map zooms. The "+" button in the chat header clears the
   thread to start a new conversation
4. Rail → Geocatalog: pick a topic (translated names), filter, add layers of
   each kind — a WMTS overlay (e.g. Wildruhezonen), a WMS layer (e.g. hail
   hazard), and a live GeoJSON layer (e.g. flood hazard levels: styled
   station icons with labels on zoom-in); the ⓘ button opens the layer-info
   dialog (description, legend, geocat/download links)
5. Rail → Displayed maps: switch Color/Grey/Aerial via the eye toggles;
   adjust layer opacity and visibility; reorder via the grip handle
   (drag-and-drop) or the arrow buttons; zoom-to-extent on vector layers.
   With more than five layers a performance hint appears. While a layer with
   a legend is visible, its legend shows automatically at the map's top-right
6. Drag the flyout's right edge to resize the panel (persists across
   reloads; double-click resets)
7. Bottom-right map controls: − / + step the zoom ladder; the locate button
   centers on your position with a marker (or reports out-of-Switzerland /
   denied access)
8. Click a feature of an identify-capable layer → popup with LV95 readout
9. Rail → Feedback: submit (entry lands in mock-agent/feedback.log)
10. Rail → About: project info panel
11. Switch the language via the rail's translate icon (de/fr/it/en/rm) →
    labels, catalog, and legends re-localize
12. Send a message containing `/error`, then one with `/slow` + cancel
13. Kill and restart the mock agent → connection badge recovers
