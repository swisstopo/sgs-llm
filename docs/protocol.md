# Agent WebSocket protocol — v1

This document is the **normative contract** between the SGS LLM frontend and
the agent backend. The frontend's canonical type definitions live in
[`frontend/src/protocol/v1.ts`](../frontend/src/protocol/v1.ts); machine-readable
JSON Schemas are in [`docs/protocol/`](./protocol/). The bundled
[`mock-agent/`](../mock-agent/) is an executable reference implementation.

## Transport

- WebSocket, JSON text frames, one event object per frame.
- The protocol version is part of the path: `wss://<host>/ws/v1`.
- No authentication (public prototype). See
  [Limits and the optional key](#limits-and-the-optional-key).
- The connection is long-lived; the client reconnects with exponential
  backoff. The server must accept multiple sequential exchanges per
  connection.

## Conversation identity

The backend groups turns to store them
([`deployment.md`](./deployment.md#what-gets-stored)), and **the client owns that
grouping**: a `user_message` may carry an optional `conversation_id`, which is the thread
the turn belongs to. The server takes it as given, for as long as the client keeps
sending it, and starts a new thread when the client sends a different one.

This is what survives a reconnect. The client reconnects with exponential backoff
(`AgentClient`) without the user noticing, and nothing on the server outlives the socket,
so an id the server derived cannot span one. Only the client knows that the chat on
screen is the same chat.

**A client that sends no `conversation_id` gets the original v1 derivation:** one
conversation per WebSocket connection, starting a new one whenever a `user_message`
arrives with empty or absent `history`. That keeps older clients and
[`mock-agent/`](../mock-agent/) working unchanged, but it splits a chat into a separate
stored thread on every reconnect, which is why a client that cares should send the field.

Whichever way the id was settled, every [`done`](#done) event carries the
`conversation_id` of the turn it terminates, so a client can always read back the thread
a turn was stored under - and that is what [feedback](#attaching-a-thread-to-feedback)
attaches to.

### What a client should send

Mint a thread id when a chat starts - `crypto.randomUUID()`, as the client already does
for `user_message.id` - and send it on every `user_message` of that chat. Mint a new one
when the user starts a new conversation (the chat header's "+"). Nothing else changes it:
not a reconnect, not an error, not a cancelled turn.

The id is a string of 1 to 64 characters. An id the server cannot use is **ignored, not
rejected**: the turn is still served, and it is grouped by the derivation above. The
server never fails a frame over this field, because a rejected frame would cost the user
the message they typed.

The server does not verify that a thread id belongs to the client sending it, and it is
not a secret - it is an analytics grouping key. Nothing is authorised by it, and no
conversation is ever served back to a client by id.

### Attaching a thread to feedback

`POST /feedback` accepts an **optional** `conversation_id` alongside the form fields,
which links the submission to the conversation the user was looking at when they wrote
it. The frontend supplies it like this:

1. Use the thread id the client minted for the chat on screen — the same value it sends
   on every `user_message`, per [What a client should send](#what-a-client-should-send).
   It covers every turn of the chat, including the ones served across a reconnect.
2. A client that mints none instead keeps the `conversation_id` of the most recent
   `done`, clearing it when the user starts a new conversation and ignoring late events
   from the previous chat. That link identifies the latest stored segment rather than
   every visible turn, because the server's own derivation starts a new thread on each
   reconnect.
3. When the feedback form is submitted, include that value in the JSON body:

   ```json
   {
     "category": "bug",
     "message": "Die Antwort war falsch.",
     "lang": "de",
     "conversation_id": "3f2a8c9e-1d4b-4f67-9a10-8c7e5d2b1a90"
   }
   ```

4. Send **no** `conversation_id` at all when there is nothing to link — a user who opens
   the feedback panel without having chatted, or after a page reload that lost the id.
   Omit the key rather than sending `null` or `""`.

The field is optional on purpose: a client that never sends one keeps working unchanged,
and the submission is stored either way. A value the server cannot use — not a string,
blank, or longer than 64 characters — is **dropped, not rejected**: the response is still
`204` and the feedback is stored without the link, because a bug in the client must not
discard what a person typed. The server logs a warning when that happens, so a frontend
that sends a malformed id will not do so unnoticed.

The id is only as trustworthy as the client that echoes it, which is fine for what it is
for: grouping a pilot's feedback with the conversation that prompted it. Nothing is
authorised by it.

The admin feedback drawer can open the linked conversation using the existing
`/admin/api/records/conversations` endpoint. It follows pagination within the dashboard's
selected dates and labels the transcript with that range. Messages outside the range
are not included; if no match is found, the administrator can widen the date selection.

## Client → server events

### `user_message`

```json
{
  "type": "user_message",
  "id": "9f1f6e8c-…",
  "content": "Zeige mir Hochwassergefahren im Wallis",
  "lang": "de",
  "model": "primary",
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
- `conversation_id` — optional; the thread this turn belongs to, 1 to 64 characters.
  See [Conversation identity](#conversation-identity) for how to choose it and what
  happens when it is absent.
- `lang` — `de | fr | it | en | rm`. Server responses (labels, markdown)
  should be in this language.
- `model` — optional model routing preference. `primary` pins the complete turn to
  Claude, `secondary` to Mistral, `apertus` to the self-hosted Apertus 1.5 endpoint.
  The server defaults to `primary` for older clients.

  `apertus` differs from the two Bedrock choices in ways a client should surface:
  it is **available on weekdays 06:40–19:00 Europe/Zurich only**, allowing ten minutes
  after the instance starts at 06:30 for model loading (see
  [Apertus operating hours](./apertus-endpoint.md#when-it-is-up)). It answers far more
  slowly (about 24 s for a 400-token answer), and serves **one conversation at a
  time** — a second concurrent request queues. Outside that window the turn ends
  with `error` `model_unavailable` and a localized message naming the schedule; it
  is never silently answered by another model. A client that offers the choice
  should either disable it out of hours or render that error as a normal state
  rather than a failure.
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

A **failed tool call arrives as `status: "failed"` on its step, not as an `error`**.
`error` is terminal, so emitting one per failed tool would end the exchange over a
single flaky call; instead the model is told the tool failed and answers around it, and
the turn still reaches `final`. Clients should therefore expect an exchange to succeed
with one or more failed steps in it. Note that this differs from the wording in
[`architecture.md`](./architecture.md#mcp-client-interface) ("failures surface as
`error`") and is not yet confirmed with the connector work package.

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
      "format": "parquet",
      "url": "https://…/data.parquet",
      "geometry_type": "polygon",
      "feature_count": 5,
      "bbox": [7.0, 46.05, 8.1, 46.35],
      "attribution": "BAFU",
      "style_hint": { "fill_color": "#1c64f2", "opacity": 0.45 }
    }
  ],
  "catalog_layers": [
    {
      "id": "ch.bafu.aquaprotect_100",
      "name": "Flooding Aquaprotect 100",
      "opacity": 0.7,
      "attribution": "geo.admin.ch"
    }
  ],
  "focus_bbox": [7.0, 46.05, 8.1, 46.35]
}
```

- `content_markdown` — GitHub-flavored markdown. The client sanitizes it;
  raw HTML is stripped.
- `layers` — optional data layers. The client fetches `url` itself (the URL
  must be CORS-accessible, e.g. a presigned object URL).
  - `format` — `geojson | parquet` (GeoParquet). This frontend supports both;
    geosearch emits GeoParquet for new chat-produced feature layers.
  - `geometry_type` — `point | line | polygon`.
  - `bbox` — WGS84, for zoom-to-layer.
  - `style_hint` — optional rendering hints: `fill_color`, `stroke_color`,
    `stroke_width`, `point_radius`, `opacity`.
- `catalog_layers` — optional structured official-layer references. When an exact layer
  title occurs in the answer, the frontend turns that title into an inline control;
  clicking it opens an anchored tooltip with “Add map layer” and “Layer details”, plus an
  × close control. When already active, the first action becomes “Remove map layer”. These
  labels deliberately differ from “Show result on map” on agent-produced data.
  The tooltip also shows the official title, layer id, and attribution. Adding resolves
  the current WMS/WMTS/GeoJSON configuration through
  `LayerService.addOfficialLayer`; tiles remain hosted by geo.admin.ch. A separate card
  is retained only as a fallback when the answer omitted the exact title.
- `focus_bbox` — optional WGS84 camera target applied after the user adds an official
  layer. A reference is an offer, not an automatic map mutation.

The WebSocket protocol intentionally describes presentation rather than MCP implementation
details. The production server's ten tool contracts and representative chains are documented
in [`mcp-tool-catalog.md`](./mcp-tool-catalog.md).

### `error`

```json
{
  "type": "error",
  "message_id": "9f1f6e8c-…",
  "code": "internal",
  "message": "human-readable description"
}
```

`code` — `internal | timeout | bad_request | cancelled | model_unavailable`.

`model_unavailable` means the explicitly requested model is not reachable and no
other model was substituted. In the pilot this is Apertus outside its office-hours
schedule, which is expected operation rather than an incident. The accompanying
`message` is localized and names when the model returns, so it can be shown as-is.
A client that does not know the code can treat it as `internal` and still display
`message` — which is what `frontend/src/protocol/v1.ts` does with any unrecognized
code.

### `done`

```json
{
  "type": "done",
  "message_id": "9f1f6e8c-…",
  "conversation_id": "3f2a8c9e-1d4b-4f67-9a10-8c7e5d2b1a90"
}
```

Always the terminal event of an exchange.

- `conversation_id` — optional; the thread this turn was grouped under, as described
  in [Conversation identity](#conversation-identity). It is the only place the client
  is told a thread id, and it is what [feedback](#attaching-a-thread-to-feedback)
  attaches to. A client that does not need it ignores it, per the forward-compatibility
  rule below.

## Exchange rules

1. Per `user_message`, the server sends zero or more `intermediate` events,
   then **exactly one** `final` **or** one `error`, then **exactly one**
   `done`.
2. Clients **ignore unknown event types and unknown fields** (forward
   compatibility). Servers must tolerate unknown fields in client events.
3. Events of one exchange arrive in order; exchanges are not interleaved on
   a single connection.

<a id="waiting-for-the-production-mcp-server"></a>

## Production MCP configuration

The backend answers only when it is connected to a real geodata MCP server
(`MCP_SERVER_URL`). Until then it **accepts connections and refuses every turn** with
one `error` (`code: "internal"`) followed by `done` - the ordinary exchange
termination, so no client change is needed and nothing hangs.

The server to point it at is [`geosearch/`](../geosearch/README.md), which this project
builds and deploys ([`deployment.md`](./deployment.md#geodata-mcp-server-geosearch-deployment)).
The refusal is what an _unconfigured_ deployment does, and it stays: the alternative was
to answer from the bundled stand-in ([`mcp_dummy/`](../mcp_dummy/README.md)), which
returns real geo.admin.ch data but is a development tool; answers sourced from it could
be mistaken for production output. Refusing is the honest default, and the map (Track A
in [`architecture.md`](./architecture.md#overview)) is unaffected - it never depended on
the agent.

Two consequences worth knowing:

- A configured-but-**unreachable** server is a different case: that still degrades
  rather than refusing. The model is told its tools are unavailable and answers what it
  can, per [`architecture.md`](./architecture.md#backend-architecture).
- The refusal lives in the transport, not the agent loop, so the evaluation harness
  ([`evals.md`](./evals.md)) can drive the loop against either its in-process stand-in or a
  running production geosearch endpoint.

## Limits and the optional key

The endpoint is unauthenticated by design, but it is not unprotected. The backend
enforces, all configurable in the task definition:

| Limit                                         | Default               | Why                                                                                                    |
| --------------------------------------------- | --------------------- | ------------------------------------------------------------------------------------------------------ |
| Accepted WebSocket origin (`ALLOWED_ORIGINS`) | the CloudFront domain | Stops a third-party page driving the socket. Browser-enforced only                                     |
| Messages per client per minute                | 20                    | Every turn spends Bedrock tokens                                                                       |
| Concurrent connections per client             | 8                     |                                                                                                        |
| Max message length / frame size               | 4 000 chars / 256 KiB |                                                                                                        |
| One in-flight exchange per connection         | -                     | The contract already forbids interleaving; a second `user_message` mid-turn gets `error` `bad_request` |
| Turn wall-clock budget                        | 90 s                  | Then `error` `timeout`. `model: "apertus"` gets 240 s, because it decodes at about 16.8 tok/s          |

Over-limit requests still terminate the exchange properly - one `error`, then `done` - so
the client never waits forever.

**The optional shared key.** `API_KEY` is empty by default, which is how the pilot is
deployed. Two things are worth stating plainly, because they are easy to get wrong:

- **The browser WebSocket API cannot set request headers.** A header-based key is
  therefore possible on `POST /feedback` but _not_ on `/ws/v1`. The server accepts
  `x-api-key` on either endpoint, and on `/ws/v1` also a `Sec-WebSocket-Protocol` entry
  of the form `sgs-llm-key.<value>`, which is the only channel a browser could use. No
  client sends it today; enabling the key needs client work first.
- **It is not a security boundary.** The frontend has to read the key from the publicly
  served `config.json`, so anyone can fetch it. It deters blind scanners and nothing
  else. What actually protects the service is the rate limiting above, plus the ALB
  admitting only the CloudFront prefix list.

The exposures worth deciding about before real users are **Bedrock spend** (an open chat
endpoint spends tokens) and **retention of whatever anyone types** (90 days, see
[`deployment.md`](./deployment.md#what-gets-stored)). Real per-user authentication, if
swisstopo wants it, belongs at CloudFront (WAF rate rules, or an identity provider), not
in a key shipped to the browser.

## Planned for v1.1 (not yet in effect)

- `final_delta` — token-level streaming of `content_markdown` before the
  consolidated `final`. Backends should be designed so the final text can
  also be streamed incrementally.
