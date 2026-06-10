# Agent WebSocket protocol — v1

This document is the **normative contract** between the SGS LLM frontend and
the agent backend. The frontend's canonical type definitions live in
[`frontend/src/protocol/v1.ts`](../frontend/src/protocol/v1.ts); machine-readable
JSON Schemas are in [`docs/protocol/`](./protocol/). The bundled
[`mock-agent/`](../mock-agent/) is an executable reference implementation.

## Transport

- WebSocket, JSON text frames, one event object per frame.
- The protocol version is part of the path: `wss://<host>/ws/v1`.
- No authentication (public prototype).
- The connection is long-lived; the client reconnects with exponential
  backoff. The server must accept multiple sequential exchanges per
  connection.

## Client → server events

### `user_message`

```json
{
  "type": "user_message",
  "id": "9f1f6e8c-…",
  "content": "Zeige mir Hochwassergefahren im Wallis",
  "lang": "de",
  "history": [
    { "role": "user", "content": "…" },
    { "role": "assistant", "content": "…" }
  ],
  "map_context": {
    "bbox": [7.0, 46.0, 8.2, 46.6],
    "active_layer_ids": ["ch.bafu.waldreservate"]
  }
}
```

- `id` — client-generated unique id. All server events for this exchange
  echo it as `message_id`.
- `lang` — `de | fr | it | en | rm`. Server responses (labels, markdown)
  should be in this language.
- `history` — optional prior exchanges, oldest first; the server is
  stateless.
- `map_context` — optional; current viewport bbox (WGS84, `[minLon, minLat,
  maxLon, maxLat]`) and active layer ids.

### `cancel`

```json
{ "type": "cancel", "id": "9f1f6e8c-…" }
```

Requests cancellation of the in-flight exchange `id`. The server responds
with `error` (`code: "cancelled"`) followed by `done`.

## Server → client events

All server events carry the `message_id` of the triggering `user_message`.

### `intermediate` — tool/work progress

```json
{
  "type": "intermediate",
  "message_id": "9f1f6e8c-…",
  "step_id": "s1",
  "status": "started",
  "label": "Suche passende Datensätze …",
  "detail": "optional extra context"
}
```

- `status` — `started | finished | failed`. Repeating a `step_id` updates
  that step (typically `started` → `finished`).
- `label` — human-readable, localized to the request `lang`.

### `final` — the answer

```json
{
  "type": "final",
  "message_id": "9f1f6e8c-…",
  "content_markdown": "## Ergebnis …",
  "layers": [
    {
      "id": "flood-zones-1",
      "name": "Hochwasser-Gefahrenzonen",
      "format": "geojson",
      "url": "https://…/data.geojson",
      "geometry_type": "polygon",
      "feature_count": 5,
      "bbox": [7.0, 46.05, 8.1, 46.35],
      "attribution": "BAFU",
      "style_hint": { "fill_color": "#1c64f2", "opacity": 0.45 }
    }
  ]
}
```

- `content_markdown` — GitHub-flavored markdown. The client sanitizes it;
  raw HTML is stripped.
- `layers` — optional data layers. The client fetches `url` itself (the URL
  must be CORS-accessible, e.g. a presigned object URL).
  - `format` — `geojson | parquet` (GeoParquet). Clients that do not
    support a format show the layer as not displayable.
  - `geometry_type` — `point | line | polygon`.
  - `bbox` — WGS84, for zoom-to-layer.
  - `style_hint` — optional rendering hints: `fill_color`, `stroke_color`,
    `stroke_width`, `point_radius`, `opacity`.

### `error`

```json
{
  "type": "error",
  "message_id": "9f1f6e8c-…",
  "code": "internal",
  "message": "human-readable description"
}
```

`code` — `internal | timeout | bad_request | cancelled`.

### `done`

```json
{ "type": "done", "message_id": "9f1f6e8c-…" }
```

Always the terminal event of an exchange.

## Exchange rules

1. Per `user_message`, the server sends zero or more `intermediate` events,
   then **exactly one** `final` **or** one `error`, then **exactly one**
   `done`.
2. Clients **ignore unknown event types and unknown fields** (forward
   compatibility). Servers must tolerate unknown fields in client events.
3. Events of one exchange arrive in order; exchanges are not interleaved on
   a single connection.

## Planned for v1.1 (not yet in effect)

- `final_delta` — token-level streaming of `content_markdown` before the
  consolidated `final`. Backends should be designed so the final text can
  also be streamed incrementally.
