# Tool selection from `sgs-llm/geosearch`

The existing SGS production MCP exposes ten tools. This exploration server has a different
boundary: portable, read-only discovery for general MCP hosts. The selection below keeps
the parts that return useful, client-neutral JSON and excludes operations coupled to the
SGS map application.

| Existing SGS tool | Decision | New surface | Reason |
| --- | --- | --- | --- |
| `search_layers` | Keep and clarify | `search_datasets` | Core dataset discovery; “dataset” is clearer to general agents than the map-rendering term “layer.” |
| `describe_layer` | Keep and clarify | `describe_dataset` | Agents need authoritative schema and metadata before interpreting fields. |
| `search_locations` | Keep and clarify | `search_divisions` | Explicitly distinguishes named areas from precise geocoding. |
| `geocode_location` | Keep | `geocode_location` | Required for addresses, parcels, postcodes, named points, WGS84, and LV95. |
| `identify_at_point` | Keep, stateless | `identify_at_point` | Useful read-only lookup after geocoding; accepts coordinates plus curated cadastral/ÖREB presets and/or exact layer IDs. |
| `display_division` | Exclude | — | Publishes a browser-specific GeoParquet layer and needs boundary artifact storage. |
| `filter_features` | Exclude | — | Bulk retrieval, exact clipping, caching, and 100k-feature limits belong to the full geospatial analysis server. |
| `display_catalog_layer` | Exclude | — | Its output is an SGS frontend action, not a portable MCP result. |
| `analyze_features` | Exclude | — | Depends on a stateful `result_id` cache created by bulk retrieval. |
| `display_layer` | Exclude | — | Depends on S3/local artifact publication and SGS map conventions. |

One small link helper completes the portable workflow. `get_map_preview_links` combines
exact dataset IDs with a resolved bbox or explicitly labelled point in universal GeoAdmin
URLs; unlike the excluded display tools, it publishes no data and returns no frontend
action. Domain explanations stay in server instructions and MCP resources so they do not
occupy the callable tool surface.

## Architectural changes

- The original semantic search uses Bedrock embeddings, FAISS, DuckDB, and a reranking
  model. This server uses a 3.2 MB multilingual catalogue snapshot plus current lexical
  SearchServer results, so it has no AWS or model dependency.
- Division search uses a 1.3 MB packaged snapshot rather than 108 MB of boundary polygons.
  It returns WGS84 bboxes and source IDs, not geometry.
- HTTP mode is explicitly stateless; there are no hidden location or feature caches.
- Dataset and point results link to the official map viewer. `get_map_preview_links` centres
  selected layers on a resolved division, while point links centre and enable the resolved
  layers without embedding geometry in the MCP response.
- Every operation is annotated read-only and non-destructive in MCP `tools/list`.
- Domain explanations are available as server instructions, resources, and tool
  descriptions without adding a redundant callable tool.
