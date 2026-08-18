# Stand-in geodata MCP server

A small compatibility MCP server exposing six geodata tools over **Streamable HTTP**,
backed by the **real public geo.admin.ch APIs**. It remains useful for backend integration
tests, evaluation fixtures, and lightweight local development. Production uses the
ten-tool [`geosearch`](../geosearch/README.md) server.

It is a *stand-in*, not a mock: its tools return genuine Swiss federal data. It deliberately
does not reproduce the production search index, authoritative geocoder, schema inspection,
point-identify, administrative-boundary display, structured filters, or advanced analysis.
Switching between servers is one environment variable: set `MCP_SERVER_URL` to the desired
endpoint and the backend discovers that server's actual tool catalogue.

> **It does not answer production traffic.** The backend refuses chat turns unless
> `MCP_SERVER_URL` names a real server, so this one serves development, the integration
> tests and the [evaluation harness](../docs/evals.md) - never the deployed pilot. Point
> `MCP_SERVER_URL` at it explicitly to develop against real geodata. The reasoning is in
> [`docs/protocol.md`](../docs/protocol.md#waiting-for-the-production-mcp-server).

## Tools

This is the six-tool compatibility subset. For the ten production tools and their full
input/output contracts, see [`docs/mcp-tool-catalog.md`](../docs/mcp-tool-catalog.md).

| Tool | Backed by | Returns |
| --- | --- | --- |
| `search_layers` | SearchServer `type=layers` | candidate `layer_id`s with titles and a trimmed abstract |
| `search_locations` | SearchServer `type=locations` | cantons / districts / communes / places → WGS84 bbox |
| `filter_features` | `MapServer/identify` as a bbox query | a `result_id` handle plus a summary of the features |
| `analyze_features` | shapely + pyproj | count, total area (km²), total length (km), extent |
| `display_layer` | the backend's artifact store | a published GeoJSON URL, bbox, geometry type and count |

Production-only tools are `geocode_location`, `describe_layer`, `identify_at_point`, and
`display_division`. Production `filter_features` additionally
supports real administrative-boundary clipping and structured schema-validated filters;
production `analyze_features` adds grouping, top values, and numeric statistics.

Two design choices are worth knowing, because a real server will face both:

- **Features never cross the wire.** `filter_features` returns a short `result_id`
  handle, and `analyze_features` / `display_layer` take it. A few hundred Swiss features are far
  larger than a small model's usable context, so round-tripping them through the model
  would be expensive and lossy.
- **Areas are measured in LV95** (EPSG:2056), not in degrees, which is the same CRS the
  map pipeline uses.

## Canton names

`origins=kantone` on the live API does **not** match every canton name in every national
language - searching for `Wallis` returns nothing and the query then falls through to the
gazetteer and finds unrelated places like *Wallisellen*. The two-letter code always
matches, so `cantons.py` translates a canton name in any national language to its code
before the lookup. Verified against the live API on 2026-07-30.

## Run it standalone

```bash
python -m mcp_dummy.server            # http://127.0.0.1:8788/mcp
python -m mcp_dummy.server --port 9000
```

Standalone it publishes layers from its own memory and serves them at
`/artifacts/<name>`, so it needs no AWS and no backend - useful for pointing another MCP
client at it.

This is how you use it locally: start it, then set `MCP_SERVER_URL=http://127.0.0.1:8788/mcp`
so the backend connects over the same Streamable HTTP path production uses.

Example compatibility query:

```text
Find municipalities named Zug, count the returned features, and prepare them for the map.
search_locations → filter_features → analyze_features → display_layer
```

The integration tests and the eval harness instead construct it **in-process** over the
MCP SDK's in-memory transport - no listener, no port, nothing exposed. That is
deliberate: serving it over loopback HTTP inside the backend was measurably fragile, as
the socket accepts connections as soon as uvicorn binds it, but requests arriving before
the ASGI lifespan has started the MCP session manager are answered without ever being
handled, so the agent silently ran with no tools. Under CPU load that happened in roughly
a third of runs. An in-memory transport has no such window.
