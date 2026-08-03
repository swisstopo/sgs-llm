# Stand-in geodata MCP server

A working MCP server exposing geodata tools over **Streamable HTTP**, backed by the
**real public geo.admin.ch APIs**. It exists so the backend's MCP client, agent loop and
evaluation harness could be built and benchmarked before swisstopo's own MCP server is
available.

It is a *stand-in for that server*, not a mock of it: the tools return genuine Swiss
federal data, so the answers are real and the whole tool contract is exercised end to
end. Replacing it is one environment variable - set `MCP_SERVER_URL` to the real
endpoint and the backend connects there instead, with no code or image change.

> **It does not answer production traffic.** The backend refuses chat turns unless
> `MCP_SERVER_URL` names a real server, so this one serves development, the integration
> tests and the [evaluation harness](../docs/evals.md) - never the deployed pilot. Point
> `MCP_SERVER_URL` at it explicitly to develop against real geodata. The reasoning is in
> [`docs/protocol.md`](../docs/protocol.md#waiting-for-the-production-mcp-server).

## Tools

| Tool | Backed by | Returns |
| --- | --- | --- |
| `search_layers` | SearchServer `type=layers` | candidate `layer_id`s with titles and a trimmed abstract |
| `search_locations` | SearchServer `type=locations` | cantons / districts / communes / places → WGS84 bbox |
| `filter_features` | `MapServer/identify` as a bbox query | a `result_id` handle plus a summary of the features |
| `compute` | shapely + pyproj | count, total area (km²), total length (km), extent |
| `display_layer` | the backend's artifact store | a published GeoJSON URL, bbox, geometry type and count |

Two design choices are worth knowing, because a real server will face both:

- **Features never cross the wire.** `filter_features` returns a short `result_id`
  handle, and `compute` / `display_layer` take it. A few hundred Swiss features are far
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

The integration tests and the eval harness instead construct it **in-process** over the
MCP SDK's in-memory transport - no listener, no port, nothing exposed. That is
deliberate: serving it over loopback HTTP inside the backend was measurably fragile, as
the socket accepts connections as soon as uvicorn binds it, but requests arriving before
the ASGI lifespan has started the MCP session manager are answered without ever being
handled, so the agent silently ran with no tools. Under CPU load that happened in roughly
a third of runs. An in-memory transport has no such window.
