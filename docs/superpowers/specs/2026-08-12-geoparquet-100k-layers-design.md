# GeoParquet 100k Chat Layers Design

## Goal

Allow the geodata MCP server to return as many as 100,000 complete vector features in
one chat-produced map layer, transfer that layer to the browser as GeoParquet instead of
GeoJSON, and explain MCP/tool failures to the user in the chat progress UI.

## Scope

This change extends the existing feature-query path:

`geo.admin.ch -> geosearch -> S3 or local artifact store -> backend protocol -> browser`

It does not add a tile server, MVT, PMTiles, pregenerated tiles, a new load balancer, or
a second data store. Official WMTS/WMS/GeoJSON catalogue layers are unchanged.

## Feature Limit

`filter_features` applies text filtering and administrative-boundary clipping before it
checks the result size. A result containing at most 100,000 features is retained in the
existing result cache. A result containing 100,001 or more features is rejected before
it enters the cache or is published.

The rejection is explicit and actionable:

> Result contains more than 100,000 features. Narrow the place, area, or dataset.

The server never publishes the first 100,000 rows of a larger result. That would make
the displayed layer, count, and later computations disagree with the real result.

## GeoParquet Artifact Contract

`display_layer` and `display_division` publish GeoParquet 1.1 files with:

- one WKB `geometry` column in OGC CRS84 axis order;
- a stable string `feature_id` column;
- scalar properties retained as Arrow boolean, integer, floating-point, or string
  columns when their values are compatible;
- nested or mixed property values represented as deterministic JSON strings;
- GeoParquet `geo` metadata declaring the primary geometry column, geometry types,
  CRS, and bounding box;
- a private `sgs:property_columns` mapping for property names that collide with
  `feature_id` or `geometry`;
- Zstandard compression and 64,000-row row groups.

The artifact is stored through the existing `ArtifactStore` abstraction. Production
uses the existing private S3 data-layer bucket and a presigned URL. Local development
uses the existing `/data/<name>` in-memory fallback. The existing S3 lifecycle policy
continues to expire published layer artifacts; this change does not persist generated
tiles because there are no generated tiles.

The protocol format value remains `parquet`, which is already accepted by the Python,
JSON Schema, and TypeScript protocol definitions. GeoJSON remains accepted for backward
compatibility and mock fixtures, but geosearch emits `parquet` for new feature layers.

## Browser Decoding

The frontend fetches the `.parquet` URL as an `ArrayBuffer` and transfers it to a
dedicated Web Worker. The worker:

1. reads the GeoParquet metadata and validates WKB geometry plus CRS84;
2. decodes rows using a pinned browser-native Parquet reader;
3. restores original property names using `sgs:property_columns`;
4. converts each WKB geometry into a serializable GeoJSON geometry; and
5. posts bounded feature chunks back to the main thread.

The main thread reprojects each chunk from EPSG:4326 to EPSG:2056 with OpenLayers and
adds it to one `VectorSource`. Chunking keeps event-loop gaps available while a large
layer is loaded. The result remains an ordinary vector layer, so the existing styling,
feature popup, visibility, opacity, and zoom-to-layer behavior continue to work.

Only one decode job owns a layer load. Removing a layer or replacing the application
session terminates its worker and ignores late chunks. Fetch, metadata, decompression,
or geometry failures produce the existing `failed` add-layer result rather than a
partially registered map layer.

## MCP and Tool Error Reporting

Tool results containing a top-level `error` string are semantic failures even when the
MCP transport itself succeeded. The backend marks their progress step as failed, sends
the same safe reason back to the model, and displays it in the progress panel. This is
how the 100,000-feature rejection reaches the user.

Unexpected transport and server exceptions remain logged with full traceback in
CloudWatch, but the browser receives only a stable message containing the tool name and
exception class. Stack traces, request payloads, AWS identifiers, signed URLs, and
credentials must not be exposed in chat.

## Testing and Acceptance

Implementation follows test-first development. The acceptance checks are:

- 100,000 features pass and 100,001 features fail before caching or publication;
- a real GeoParquet file preserves IDs, properties, geometry, CRS84 metadata, bbox,
  compression, and row-group boundaries;
- S3 and local publishing use `.parquet`, the Parquet media type, and unchanged URL
  behavior;
- the backend relays `format: "parquet"` and treats a tool `error` payload as a failed
  progress step with the actionable detail;
- the worker decodes real Point, LineString, Polygon, multi-geometry, null-property,
  reserved-name, mixed-property, and 100,000-row files;
- the browser adds a real 100,000-feature layer without unsupported-format UI, preserves
  styling and click attributes, and remains responsive during loading;
- Python tests, type checks, lint, frontend unit tests, formatting, and production builds
  pass locally;
- the deployed ECS backend and geosearch revisions become healthy, the frontend is
  served through CloudFront, and one live chat request produces a fetchable GeoParquet
  layer while an over-limit controlled test shows the safe error reason.

## Delivery

Work is based on current `main` in an isolated `feature/geoparquet-100k` branch. Commits
are separated by contract, producer, backend error propagation, frontend decoder, and
deployment verification where those boundaries remain independently testable. Images
are built for `linux/amd64`, pushed under immutable commit tags, deployed through the
existing ECS task-definition flow, and verified before the prior revisions are treated
as superseded.
