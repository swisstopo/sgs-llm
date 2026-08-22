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

## Tool inputs and outputs

All six tools are read-only and return schema-validated structured JSON. Supported
response languages are `de`, `fr`, `it`, `rm`, and `en`. Point inputs are objects with an
explicit CRS and axis names: WGS84 longitude/latitude (`EPSG:4326`) or Swiss LV95
easting/northing (`EPSG:2056`).

Version 3 removes the redundant `explain_swisstopo` tool (the guides remain available as
resources), renames the read-only map helper to `get_map_preview_links`, and replaces
unlabelled point arguments with explicit coordinate objects. MCP clients refresh the tool
catalogue when they reconnect; hard-coded callers must update these names and arguments.

### `search_datasets`

- **Input:** `query` (required subject only), `language="en"`, `limit=8` (`1-20`), and
  `queryable_only=false`.
- **Output:** `datasets[]` with `dataset_id`, title/summary, capability flags, relevance,
  source information, and a nationwide `map_preview_url`; also `result_count`,
  `low_confidence`, `score_margin`, and live-catalog status.
- **Use it for:** finding official `ch.*` layers. Search for `buildings`, not
  `buildings in Olten`; resolve the place separately.

### `describe_dataset`

- **Input:** `dataset_id` (required official `ch.*` identifier) and `language="en"`.
- **Output:** `dataset` with current metadata, schema/fields, data owner, timestamps,
  legend/details/download links, query/display capability, and `map_preview_url`;
  `live_metadata` reports whether current metadata was available.
- **Use it for:** checking what a dataset actually contains before interpreting fields or
  claiming that it supports point queries.

### `search_divisions`

- **Input:** `query` (required place name), optional `kinds[]`, optional canton name/code,
  and `limit=10` (`1-50`). Valid kinds are `land`, `kanton`, `bezirk`, `gemeinde`,
  `kommunanz`, `kantonsgebiet`, and `ortschaft`.
- **Output:** `divisions[]` with `division_ref`, `name`, `kind`, `canton`, WGS84 `bbox`,
  source layer, feature count, and match score/basis; also `result_count` and snapshot date.
- **Use it for:** named areas and map focus. A bbox is an enclosing rectangle, not the
  exact administrative polygon.

### `get_map_preview_links`

- **Input:** `dataset_ids` (required, `1-10`) and exactly one focus: either WGS84
  `focus_bbox=[west,south,east,north]` or a `point` object explicitly labelled as
  WGS84 longitude/latitude or LV95 easting/northing; optional `language="en"`.
- **Output:** `individual_links[]` containing one centred official URL per dataset,
  optional `combined_link`, original `focus`, and the exact LV95 `center` used by the
  map viewer.
- **Use it for:** subject-plus-place questions. Present every individual preview link;
  never replace them with only the combined link.

### `geocode_location`

- **Input:** `query` (required), optional `origins[]`, `language="en"`, and `limit=5`
  (`1-20`). Origins are `address`, `parcel`, `zipcode`, `gazetteer`, `gg25`, `district`,
  and `kantone`.
- **Output:** `locations[]` with `location_ref`, kind, label, match quality, related
  features, explicit WGS84 and LV95 coordinates, and `map_preview_url`.
- **Use it for:** a precise address, parcel, postcode, or named point. Pass either returned
  coordinate object—not `location_ref`—to `identify_at_point`.

### `identify_at_point`

- **Input:** required explicit WGS84 or LV95 `point`; one or both of `preset` and
  `dataset_ids[]` (maximum `10`); `language="en"`; `limit=20` (`1-200`). Presets are
  `parcel`, `oereb`, and `all_relevant`.
- **Output:** `point`, resolved `selection`, `dataset_ids`, `feature_count`, `features[]`
  with full attributes and official links, plus point-centred `map_preview_url` and
  optional per-feature `map_feature_url`. `geometry_omitted` is always `true`.
- **Use it for:** parcel/EGRID attributes, ÖREB availability and official extract links,
  or feature records from an already-selected queryable layer.

Tool-level validation failures use one predictable shape (arguments rejected directly by
the advertised JSON Schema are returned as MCP protocol errors):

```json
{
  "error": {
    "code": "invalid_coordinates",
    "message": "point must lie within the Swiss map extent.",
    "retryable": false,
    "upstream_status": null
  }
}
```

Explanations are kept out of the callable tool list. The server publishes them as MCP
resources at `swisstopo://guide/{topic}` and
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

## Agent tutorial

Once the connector is installed, the model sees the tool descriptions and server
instructions automatically. For an agent framework that accepts additional instructions,
use this compact policy:

```text
Use the Swisstopo MCP for Swiss geodata exploration.
Keep dataset subjects separate from place names: search the subject with search_datasets
and resolve the place with search_divisions. For subject-plus-place questions, call
get_map_preview_links and return every individual dataset link. Use geocode_location
before identify_at_point for an address. Use parcel, oereb, or all_relevant for cadastral
questions. Copy returned map URLs verbatim. Never invent dataset IDs or coordinates, swap
longitude/latitude, or claim that the MCP returned geometry or GeoJSON.
```

### Complete Agno agent with AWS Bedrock

Create a separate Agno client environment because Agno 2.9.0 currently uses the MCP 1.x
Python client while this server uses MCP 2.0 internally:

```bash
python3.12 -m venv .venv-agno-client
.venv-agno-client/bin/pip install \
  agno==2.9.0 mcp==1.29.0 boto3==1.40.61 aioboto3==15.5.0
```

Configure the standard AWS credential chain (`AWS_PROFILE`, or `AWS_ACCESS_KEY_ID` and
`AWS_SECRET_ACCESS_KEY`) and run this example:

```bash
# Only needed when an existing .env uses AWS_ACCESS_KEY instead of the standard name.
export AWS_ACCESS_KEY_ID="$AWS_ACCESS_KEY"
```

```python
import asyncio
import os

from agno.agent import Agent
from agno.models.aws import AwsBedrock
from agno.tools.mcp import MCPTools

MCP_URL = "https://denpw8uo5zpkl.cloudfront.net/mcp"


async def main() -> None:
    async with MCPTools(transport="streamable-http", url=MCP_URL) as swisstopo:
        agent = Agent(
            name="Swisstopo explorer",
            model=AwsBedrock(
                id=os.getenv(
                    "BEDROCK_PRIMARY_MODEL_ID",
                    "eu.anthropic.claude-sonnet-4-6",
                ),
                aws_region=os.getenv("BEDROCK_REGION", "eu-central-1"),
                temperature=0,
                max_tokens=2048,
            ),
            tools=[swisstopo],
            instructions=[
                "Use the Swisstopo tools for Swiss geodata questions.",
                "Search dataset subjects and geographic divisions separately.",
                "Return every individual get_map_preview_links URL.",
                "Geocode an address before parcel or ÖREB identification.",
                "Use returned map URLs verbatim and never claim geometry was returned.",
            ],
            markdown=True,
        )
        await agent.aprint_response(
            "Show me building datasets in Olten and give me a separate centred map link "
            "for each dataset.",
            stream=True,
        )


asyncio.run(main())
```

The `async with` block is important: it opens the MCP connection before the agent runs
and closes it cleanly afterwards. The MCP itself does not use Bedrock; only the Agno agent
uses the selected model.

### Workflow 1: datasets in a named place

User query:

```text
Show me building datasets in Olten. Give me a separate map link for each one.
```

The reliable tool sequence is:

1. Search only the subject.

   ```json
   {
     "name": "search_datasets",
     "arguments": {"query": "buildings", "language": "en", "limit": 5}
   }
   ```

2. Resolve the town as a municipality.

   ```json
   {
     "name": "search_divisions",
     "arguments": {"query": "Olten", "kinds": ["gemeinde"], "limit": 3}
   }
   ```

   The selected result includes a WGS84 bbox similar to:

   ```json
   {
     "division_ref": "division:...",
     "name": "Olten",
     "kind": "gemeinde",
     "canton": "SO",
     "bbox": [7.874858, 47.311028, 7.929085, 47.368924]
   }
   ```

3. Combine the selected dataset IDs with that complete bbox.

   ```json
   {
     "name": "get_map_preview_links",
     "arguments": {
       "dataset_ids": [
         "ch.bfs.gebaeude_wohnungs_register",
         "ch.swisstopo.vec25-gebaeude"
       ],
       "focus_bbox": [7.874858, 47.311028, 7.929085, 47.368924],
       "language": "en"
     }
   }
   ```

   Important output shape:

   ```json
   {
     "individual_links": [
       {
         "dataset_id": "ch.bfs.gebaeude_wohnungs_register",
         "url": "https://map.geo.admin.ch/#/map?..."
       },
       {
         "dataset_id": "ch.swisstopo.vec25-gebaeude",
         "url": "https://map.geo.admin.ch/#/map?..."
       }
     ],
     "combined_link": "https://map.geo.admin.ch/#/map?...",
     "center": {"easting": 2635016.954, "northing": 1243338.4, "crs": "EPSG:2056"}
   }
   ```

The final answer should contain two individually labelled URLs. The combined URL may be
listed afterwards as an optional convenience.

### Workflow 2: parcel and ÖREB details for an address

User query:

```text
Find the parcel and ÖREB information for Seftigenstrasse 264, 3084 Wabern.
```

First geocode the precise address:

```json
{
  "name": "geocode_location",
  "arguments": {
    "query": "Seftigenstrasse 264, 3084 Wabern",
    "origins": ["address"],
    "language": "en",
    "limit": 1
  }
}
```

The result contains both coordinate systems. Copy either complete object into the next
tool call; this example uses WGS84:

```json
{
  "coordinates": {
    "wgs84": {
      "longitude": 7.451352,
      "latitude": 46.927937,
      "crs": "EPSG:4326"
    },
    "lv95": {
      "easting": 2600968.7,
      "northing": 1197426.9,
      "crs": "EPSG:2056"
    }
  }
}
```

Then request both cadastral and ÖREB records:

```json
{
  "name": "identify_at_point",
  "arguments": {
    "point": {
      "longitude": 7.451352,
      "latitude": 46.927937,
      "crs": "EPSG:4326"
    },
    "preset": "all_relevant",
    "language": "en",
    "limit": 20
  }
}
```

The response includes `features[]`, full record properties, `external_links`, a
point-centred `map_preview_url`, and official cantonal ÖREB PDF/web links when available.
It deliberately returns `"geometry_omitted": true`. Treat the official cantonal extract,
not the exploratory MCP response, as authoritative.

## Test-query suite

Use these prompts in Claude, Agno, or another connected agent. The expected behavior is
more important than exact wording because the public catalogue can change.

| Difficulty | Test query | Expected tools and checks |
| --- | --- | --- |
| Basic | `What can this Swisstopo MCP do?` | Use server instructions/tool descriptions; explain exploration limits without inventing analysis tools. |
| Basic | `Find official avalanche-hazard datasets.` | `search_datasets`; return real `ch.*` IDs and mention low confidence if reported. |
| Place | `Show me building datasets in Olten, with one centred link per dataset.` | `search_datasets` + `search_divisions` + `get_map_preview_links`; choose `gemeinde`; return every individual link. |
| Metadata | `What fields and owner does ch.bfs.gebaeude_wohnungs_register have?` | `describe_dataset`; use returned fields/owner rather than assumptions. |
| Multilingual | `Trouve des données sur le potentiel solaire à Genève.` | French dataset search plus Geneva division resolution; keep subject and place separate. |
| Ambiguity | `Show data for Zürich.` | Resolve or clarify canton/district/commune/locality instead of silently selecting one. |
| Address | `Map Bundesplatz 3, Bern.` | `geocode_location` with `origins=["address"]`; return the supplied point preview URL verbatim. |
| Cadastral | `Find parcel and ÖREB details for Seftigenstrasse 264, 3084 Wabern.` | Geocode, then `identify_at_point` with `all_relevant`; include official extract links and no geometry. |
| Exact point | `What parcel is at 7.451352, 46.927937?` | `identify_at_point` with `parcel`; preserve longitude/latitude order. |
| Comparison | `Compare the building register and VECTOR25 buildings over Olten.` | Describe both datasets, resolve Olten, and provide two individual previews plus optional combined view. |
| Capability | `Identify features in a raster aerial-image layer at this point.` | Check `queryable`; explain that raster layers may display but do not support feature identification. |
| Coordinate trap | `Use 2600968,1197427 as longitude and latitude.` | Refuse the invalid WGS84 interpretation; explain that these are likely LV95 metre coordinates. |
| Scope boundary | `Download every building as GeoJSON and clip it to Olten.` | Explain that bulk retrieval, GeoJSON, clipping, and analysis belong to the full geosearch service. |
| Legal caution | `Is this ÖREB response legally authoritative?` | Say no; direct the user to the returned official cantonal PDF/web extract. |
| Recovery | `Find buildings in a Swiss place that does not exist.` | Return/acknowledge no division match and ask for a valid or less ambiguous place. |

A good agent run has these properties:

- it never invents a dataset ID, coordinate, field, or administrative relationship;
- it separates a dataset subject from a geographic place;
- it uses `get_map_preview_links` for place-centred dataset links;
- it returns every requested individual map link and copies URLs verbatim;
- it labels every point as WGS84 or LV95 and never swaps or guesses coordinate axes;
- it clearly states that geometry, GeoJSON, bulk downloads, and legal certificates are
  outside this MCP's output.

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
- Division bboxes use WGS84 (`EPSG:4326`). Point inputs and outputs support explicitly
  labelled WGS84 or LV95 (`EPSG:2056`) coordinates with named axes.
- Dataset search/description, geocoding, and point-identification results include a
  ready-to-open `map_preview_url` for the official geo.admin.ch viewer. Dataset-only links
  show Switzerland. For requests such as "buildings in Olten", `get_map_preview_links`
  combines the chosen `ch.*` IDs with the selected division bbox and returns one labelled
  preview per dataset, plus an optional combined view. Every link automatically uses an
  LV95 centre and area-appropriate zoom. Point links use an LV95 marker.
- `identify_at_point` accepts the curated `parcel`, `oereb`, and `all_relevant` presets,
  while still accepting exact `ch.*` dataset IDs. It returns attributes and official
  web/PDF links but deliberately never returns geometry or GeoJSON.
- The HTTP MCP transport is stateless. `location_ref` is a result identifier, not hidden
  server state; pass either returned coordinate object to `identify_at_point`.
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

# Exercise every tool against the deployed Streamable HTTP server.
.venv/bin/python scripts/smoke_http.py \
  https://denpw8uo5zpkl.cloudfront.net/mcp

# Verify discovery and a real tool call through Agno without spending model tokens.
.venv-agno-client/bin/python scripts/smoke_agno.py \
  https://denpw8uo5zpkl.cloudfront.net/mcp
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

The MCP itself requires no API key or AWS credentials. A model-backed agent may still
need credentials for its chosen model provider, as in the Bedrock tutorial above.

## Attribution and limitations

Data and API responses are attributed to **swisstopo / geo.admin.ch** and their named data
owners. Search results are discovery aids, not legal or cadastral certificates. A division
bbox encloses a place but does not represent its exact boundary. For bulk feature retrieval,
boundary clipping, analysis, or map-layer publishing, use the full `sgs-llm/geosearch`
server; those operations are intentionally outside this search MCP.
