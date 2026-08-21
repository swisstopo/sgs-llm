# Swisstopo Search MCP

A portable, read-only Model Context Protocol server for discovering Swiss federal
geodata. Its package does not depend on the application's model, S3 artifacts, database,
or in-memory result handles. The public production app is mounted into the already-running
SGS backend process to avoid paying for separate compute.

The same server supports both standard MCP transports:

- **stdio** for a local process launched by Claude Code or another desktop agent.
- **Stateless Streamable HTTP** at `/mcp` for Claude web connectors, Claude Code, Agno,
  and other remote MCP clients.

The current public deployment is available at:

```text
MCP: https://denpw8uo5zpkl.cloudfront.net/mcp
```

It is intentionally authless, stays warm in the existing Fargate backend, and has
independent per-viewer rate and global concurrency limits. See the
[deployment and operations guide](../docs/exploration-mcp-deployment.md) before exposing
it to high-volume traffic. Relevant pushes to `main` test the package, build it into the
backend image, and roll the ECS service automatically.

## Selected tool surface

| Tool | Purpose |
| --- | --- |
| `search_datasets` | Search official `ch.*` datasets/layers by subject, with query/display capability. |
| `describe_dataset` | Read current dataset metadata, schema, fields, timestamps, owner, legend, and links. |
| `search_divisions` | Resolve Switzerland, cantons, districts, communes, special territories, and localities. |
| `create_map_preview` | Create a separate centred GeoAdmin link per dataset, plus an optional combined view. |
| `geocode_location` | Resolve an address, parcel, postcode, canton, or named point to WGS84 and LV95. |
| `identify_at_point` | Explore a point using `parcel`, `oereb`, or `all_relevant`, and/or exact dataset IDs. |
| `explain_swisstopo` | Explain datasets, divisions, geocoding, and coordinate conventions to tools-only clients. |

The server also publishes MCP resources at `swisstopo://guide/{topic}` and
`swisstopo://catalog/stats`, plus a `find_swiss_geodata` prompt. The same critical
instructions are repeated in tool descriptions because not every MCP host exposes
resources or prompts to its model.

See [tool selection](docs/tool-selection.md) for the review of the original ten SGS tools
and [the agent guide](docs/agent-guide.md) for the domain model.

## Quick start

Python 3.12 or newer is required.

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
```

Run a remote/local HTTP endpoint:

```bash
.venv/bin/swisstopo-search-mcp --transport http --host 127.0.0.1 --port 8791
curl http://127.0.0.1:8791/health
```

The MCP URL is:

```text
http://127.0.0.1:8791/mcp
```

Run it as a local stdio subprocess instead:

```bash
.venv/bin/swisstopo-search-mcp --transport stdio
```

Logging goes to stderr, so stdout stays valid MCP JSON-RPC in stdio mode.

## Connect clients

### Claude Code — HTTP

Use the public deployment:

```bash
claude mcp add --transport http swisstopo-search \
  https://denpw8uo5zpkl.cloudfront.net/mcp
```

Or, with a local HTTP server running:

```bash
claude mcp add --transport http swisstopo-search http://127.0.0.1:8791/mcp
```

Or copy [examples/claude-code-http.mcp.json](examples/claude-code-http.mcp.json) to a
project's `.mcp.json`.

### Claude Code — stdio

Use absolute paths so Claude Code can start the server from any project:

```bash
claude mcp add --transport stdio swisstopo-search -- \
  /absolute/path/sgs-llm/exploration-mcp/.venv/bin/python \
  -m swisstopo_mcp --transport stdio
```

### Claude on the web

Claude web connectors cannot reach `127.0.0.1`. Add the production
`https://denpw8uo5zpkl.cloudfront.net/mcp` URL under
**Settings → Connectors → Add custom connector**. This server is authless because every
operation is read-only and its upstream data is public. Before a broad public launch,
decide whether organizational access requires OAuth or additional edge controls.

### Agno

As of **2026-08-21**, Agno 2.9.0 imports the MCP 1.x Python client API. Keep the Agno
client in a separate environment from this MCP 2.0 server:

```bash
python3.12 -m venv .venv-agno-client
.venv-agno-client/bin/pip install -r examples/requirements-agno-client.txt
```

The minimal connection is:

```python
from agno.tools.mcp import MCPTools

mcp_tools = MCPTools(
    transport="streamable-http",
    url="https://denpw8uo5zpkl.cloudfront.net/mcp",
)
await mcp_tools.connect()
```

A complete lifecycle-safe example is in [examples/agno_client.py](examples/agno_client.py).
The model-backed example additionally needs its model provider package and credentials.
The framework-only check in [scripts/smoke_agno.py](scripts/smoke_agno.py) was tested
against this server and does not need an LLM key.

### MCP Inspector

```bash
npx -y @modelcontextprotocol/inspector \
  --server-url https://denpw8uo5zpkl.cloudfront.net/mcp \
  --transport http
```

Use the inspector to verify initialization, `tools/list`, resources, prompts, and direct
tool calls.

Compatibility references: [MCP transport specification](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports),
[Claude Code MCP configuration](https://code.claude.com/docs/en/mcp),
[Claude remote connectors](https://support.anthropic.com/en/articles/11503834-building-custom-integrations-via-remote-mcp-servers),
and [Agno Streamable HTTP](https://docs.agno.com/tools/mcp/transports/streamable_http).

## Docker

```bash
docker build -t swisstopo-search-mcp .
docker run --rm -p 8000:8000 \
  -e SWISSTOPO_MCP_ALLOWED_HOSTS=localhost:8000,127.0.0.1:8000 \
  swisstopo-search-mcp
```

For `mcp.example.ch`, configure the reverse proxy for HTTPS and set:

```text
SWISSTOPO_MCP_ALLOWED_HOSTS=mcp.example.ch,mcp.example.ch:443
SWISSTOPO_MCP_ALLOWED_ORIGINS=https://claude.ai
```

Do not use a wildcard host in production. The MCP transport validates Host and Origin to
reduce DNS-rebinding risk.

## Data and behavior

- `datasets.json` packages 896 official catalogue layers. It combines the tested SGS
  catalogue index with German, French, and English descriptions. Dataset search also
  merges the live language-specific SearchServer, including Italian and Romansh results,
  when geo.admin.ch is reachable.
- `divisions.json` packages 6,272 records: Switzerland, 26 cantons, 135 districts, 2,123
  communes, two shared territories, 11 special canton territories, and 3,974 localities.
- Division bboxes and all point inputs/outputs use WGS84 (`EPSG:4326`). Geocoding also
  returns LV95 (`EPSG:2056`) with explicitly named axes.
- Dataset search/description, geocoding, and point-identification results include a
  ready-to-open `map_preview_url` for the official geo.admin.ch viewer. Dataset-only links
  show Switzerland. For requests such as "buildings in Olten", `create_map_preview`
  combines the chosen `ch.*` IDs with the selected division bbox and returns one labelled
  preview per dataset, plus an optional combined view. Every link automatically uses an
  LV95 centre and area-appropriate zoom. Point links use an LV95 marker.
- `identify_at_point` accepts the curated `parcel`, `oereb`, and `all_relevant` presets,
  while still accepting exact `ch.*` dataset IDs. It returns attributes and official
  web/PDF links but deliberately never returns geometry or GeoJSON.
- The HTTP MCP transport is stateless. `location_ref` is a result identifier, not hidden
  server state; pass the returned WGS84 coordinates to `identify_at_point`.
- Network calls are restricted in code to the public `api3.geo.admin.ch` service.

Rebuild packaged data after refreshing the SGS source index:

```bash
.venv/bin/python scripts/build_snapshot.py \
  --database ../index/geosearch.duckdb \
  --catalog /path/to/swisstopo_catalog/described_catalog.json
```

## Test

```bash
.venv/bin/pytest -q
.venv/bin/ruff check .
```

The test suite covers offline retrieval, division aliases and hierarchy, live-response
parsing with a fake HTTP transport, the MCP tool/resource catalogue, and input validation.
The live smoke test commands in the final section of [the agent guide](docs/agent-guide.md)
exercise the real public API and Streamable HTTP endpoint.

## Environment variables

| Variable | Default | Meaning |
| --- | --- | --- |
| `SWISSTOPO_MCP_TRANSPORT` | `stdio` | `stdio`, `http`, or `streamable-http`. |
| `SWISSTOPO_MCP_HOST` | `127.0.0.1` | HTTP bind address. |
| `SWISSTOPO_MCP_PORT` | `8791` | HTTP port. |
| `SWISSTOPO_MCP_LOG_LEVEL` | `info` | `debug`, `info`, `warning`, or `error`. |
| `SWISSTOPO_MCP_ALLOWED_HOSTS` | loopback hosts | Comma-separated additional Host values. |
| `SWISSTOPO_MCP_ALLOWED_ORIGINS` | loopback origins | Comma-separated additional Origin values. |

No API key or AWS credentials are required.

## Attribution and limitations

Data and API responses are attributed to **swisstopo / geo.admin.ch** and their named data
owners. Search results are discovery aids, not legal or cadastral certificates. A division
bbox encloses a place but does not represent its exact boundary. For bulk feature retrieval,
boundary clipping, analysis, or map-layer publishing, use the full `sgs-llm/geosearch`
server; those operations are intentionally outside this search MCP.
