## Two map-layer types

The application deliberately distinguishes two kinds of map output:

| Layer type | Created by | User interface | Meaning |
|---|---|---|---|
| **Personalized result layer** | `display_layer` or `display_division` | A card below the answer with **Show result on map** | A point, parcel, boundary, or filtered feature set created specifically for the user's request. |
| **Official map layer** | `display_catalog_layer` | Clickable official layer title with **Add map layer** and **Layer details** | An existing nationwide WMS, WMTS, or GeoJSON layer whose tiles remain hosted by geo.admin.ch. |

A `result_id` is a temporary server-side handle. It must be copied exactly and used in the same running MCP service; clients must never invent or modify one.

## Tool summary

| Tool | One-sentence description |
|---|---|
| `search_layers` | Finds official Swiss geodata layers by subject using multilingual semantic and catalogue search. |
| `geocode_location` | Resolves an address, parcel, postcode, or named point and prepares a personalized point-marker result. |
| `describe_layer` | Returns detailed metadata, capabilities, schema, fields, time information, and service links for an official layer. |
| `identify_at_point` | Retrieves complete feature properties and official links from selected layers at an exact coordinate or geocoded location. |
| `search_locations` | Resolves Swiss cantons, districts, communes, localities, and the country to named areas and bounding boxes. |
| `display_division` | Prepares an official administrative boundary as a personalized GeoParquet result layer. |
| `filter_features` | Retrieves all queryable features inside a named boundary or map bounding box, with safe attribute and time filters. |
| `display_catalog_layer` | Offers an official WMS, WMTS, or GeoJSON catalogue layer for optional addition to the map. |
| `analyze_features` | Computes counts, measurements, extents, groups, frequent values, and numeric statistics over a fetched result. |
| `display_layer` | Publishes a fetched or identified feature result as a personalized GeoParquet layer. |

---

## 1. `search_layers`

**What it does:** Finds official Swiss datasets for a subject and reports whether each result can be queried feature-by-feature or displayed as a map layer.

### Input

| Field | Type | Required | Description |
|---|---:|:---:|---|
| `query` | string | Yes | Subject only, such as `flooding`, `avalanche hazards`, or `solar potential`; do not include the place name. |
| `lang` | `de \| fr \| it \| rm \| en` | No | Requested language; default is `de`. |
| `top_n` | integer | No | Maximum number of relevant results; default is 8. |

### Output

```json
{
  "layers": [
    {
      "layer_id": "ch.bafu.hydroweb-warnkarte_national",
      "title": "Flood warning map",
      "summary": "…",
      "queryable": false,
      "displayable": true,
      "data_owner": "Federal Office for the Environment FOEN",
      "similarity": 0.9
    }
  ],
  "top_score": 0.9,
  "margin": 0.1,
  "low_confidence": false,
  "layer_refs": [
    { "id": "ch.bafu.hydroweb-warnkarte_national", "name": "Flood warning map" }
  ]
}
```

### Customer query

> What official Swiss datasets are available about avalanche hazards?

### Configuration acceptance tests

| Case | Direct MCP input | Expected check |
|---|---|---|
| English | `{"query":"flood hazards","lang":"en","top_n":8}` | Relevant FOEN flood layers are returned. |
| French fallback | `{"query":"dangers de crues","lang":"fr","top_n":8}` | Localized flood layers are returned, not an empty result. |
| Italian | `{"query":"pericolo di piena","lang":"it","top_n":3}` | At most three relevant results are returned. |
| Romansh | `{"query":"privels d'inundaziun","lang":"rm","top_n":8}` | Relevant results are returned even when catalogue titles use another national language. |
| Exact layer ID | `{"query":"ch.bafu.hydroweb-warnkarte_national","lang":"en","top_n":1}` | The exact layer ranks first. |
| No meaningful match | `{"query":"saffron risotto recipe","lang":"en","top_n":8}` | Empty results or an explicit no-match note; no invented dataset. |

---

## 2. `geocode_location`

**What it does:** Resolves a precise Swiss location in WGS84 and LV95 and returns a `result_id` for a personalized point marker.

### Input

| Field | Type | Required | Description |
|---|---:|:---:|---|
| `query` | string | Yes | Address, parcel, postcode, or named point. |
| `origins` | string array | No | Any of `address`, `parcel`, `zipcode`, `gazetteer`, `gg25`, `district`, or `kantone`. |
| `lang` | language code | No | Response language; default is `de`. |
| `limit` | integer | No | Maximum candidates; default is 5. |

### Output

```json
{
  "locations": [
    {
      "location_ref": "address:1272199_0",
      "kind": "address",
      "label": "Seftigenstrasse 264 3084 Wabern",
      "coordinates": {
        "wgs84": { "longitude": 7.451352, "latitude": 46.927937 },
        "lv95": { "easting": 2600968.69, "northing": 1197426.89 }
      },
      "match_quality": "exact",
      "result_id": "fs_…",
      "display_scope": "geocoded_point",
      "related_features": []
    }
  ]
}
```

### Customer query

> Find the exact coordinates of Seftigenstrasse 264, 3084 Wabern.

Follow with:

> Show me on the map.

The follow-up must create a **Personalized result layer** containing one address point, not substitute the nationwide address-register layer.

### Configuration acceptance tests

| Case | Direct MCP input | Expected check |
|---|---|---|
| Exact address | `{"query":"Seftigenstrasse 264, 3084 Wabern","origins":["address"],"lang":"en","limit":5}` | Exact match, both CRS values, official references, and a displayable `result_id`. |
| Postcode | `{"query":"3084 Wabern","origins":["zipcode"],"lang":"en","limit":5}` | Postcode/locality candidates are returned. |
| Parcel | `{"query":"Köniz parcel 212","origins":["parcel"],"lang":"de","limit":5}` | Parcel candidates are returned when the official search can resolve the designation. |
| Broad named point | `{"query":"Matterhorn","origins":["gazetteer","gg25"],"lang":"en","limit":5}` | Named geographic candidates are returned. |
| Single candidate | `{"query":"Bundesplatz 3 Bern","origins":["address"],"lang":"en","limit":1}` | No more than one result. |
| Invalid origin | `{"query":"Bern","origins":["unsupported"]}` | Explicit validation error. |
| Empty query | `{"query":""}` | Explicit validation error; no external request is fabricated. |

---

## 3. `describe_layer`

**What it does:** Inspects an official layer before querying or presenting it.

### Input

| Field | Type | Required | Description |
|---|---:|:---:|---|
| `layer_id` | string | Yes | Official `ch.*` layer identifier. |
| `lang` | language code | No | Metadata language. |

### Output

```json
{
  "layer": {
    "layer_id": "ch.swisstopo-vd.stand-oerebkataster",
    "title": "Availability of the ÖREB cadastre",
    "description": "…",
    "owner": "swisstopo",
    "queryable": true,
    "displayable": true,
    "layer_type": "wms",
    "geometry_type": "esriGeometryPolygon",
    "fields": [
      { "name": "oereb_extract_pdf", "alias": "…", "type": "VARCHAR" },
      { "name": "oereb_extract_url", "alias": "…", "type": "VARCHAR" }
    ],
    "legend_url": "https://…",
    "details_url": "https://…",
    "download_url": "https://…"
  }
}
```

### Customer query

> Describe the layer `ch.swisstopo-vd.stand-oerebkataster`, including its fields, owner, map service, legend, and download options.

### Configuration acceptance tests

| Case | Direct MCP input | Expected check |
|---|---|---|
| ÖREB schema | `{"layer_id":"ch.swisstopo-vd.stand-oerebkataster","lang":"en"}` | Complete schema includes both ÖREB extract fields. |
| Queryable vector | `{"layer_id":"ch.swisstopo.swissboundaries3d-gemeinde-flaeche.fill","lang":"de"}` | Query and geometry capabilities are present. |
| Raster/tiles | `{"layer_id":"ch.bafu.hydroweb-warnkarte_national","lang":"fr"}` | Display capability and rendering metadata are present. |
| Unknown ID | `{"layer_id":"ch.invalid.does-not-exist","lang":"en"}` | Explicit unknown-layer error. |

---

## 4. `identify_at_point`

**What it does:** Retrieves complete feature records and official external links at one exact WGS84 point.

### Input

| Field | Type | Required | Description |
|---|---:|:---:|---|
| `layer_ids` | string array | Yes | Between 1 and 10 official `ch.*` layer IDs. |
| `location_ref` | string | Conditional | Reference returned by `geocode_location`; preferred over explicit coordinates. |
| `longitude` | number | Conditional | WGS84 longitude when no `location_ref` is used. |
| `latitude` | number | Conditional | WGS84 latitude when no `location_ref` is used. |
| `lang` | language code | No | Response language. |
| `return_geometry` | boolean | No | When true, geometry is cached and a displayable `result_id` is returned. |
| `limit` | integer | No | Maximum records, capped at 200; default is 20. |

### Output

```json
{
  "point": { "longitude": 7.451352, "latitude": 46.927937 },
  "feature_count": 2,
  "result_id": "fs_…",
  "display_feature_count": 1,
  "display_scope": "oereb_parcel",
  "features": [
    {
      "feature_ref": {
        "layer_id": "ch.swisstopo-vd.stand-oerebkataster",
        "feature_id": "865114"
      },
      "properties": {
        "egris_egrid": "CH669746359158",
        "oereb_extract_pdf": "https://…",
        "oereb_extract_url": "https://…"
      },
      "external_links": [
        { "kind": "pdf", "url": "https://…" },
        { "kind": "web", "url": "https://…" }
      ]
    }
  ]
}
```

Geometry is retained in the MCP result cache rather than sent through the model. For ÖREB, the display result selects the exact EGRID parcel polygon instead of the enclosing municipality polygon.

### Customer query

> At Seftigenstrasse 264, Wabern, return the complete ÖREB record, EGRID, PDF extract, online extract, and prepare the exact parcel polygon for the map.

### Configuration acceptance tests

| Case | Direct MCP input | Expected check |
|---|---|---|
| Geocode reference | `{"layer_ids":["ch.swisstopo-vd.stand-oerebkataster"],"location_ref":"<from geocode>","lang":"de","return_geometry":false,"limit":20}` | Complete properties and external links; no generated geometry result required. |
| Explicit coordinates | `{"layer_ids":["ch.swisstopo-vd.stand-oerebkataster"],"longitude":7.451352,"latitude":46.927937,"lang":"en","return_geometry":false}` | Same EGRID as the reference-based request. |
| Personalized parcel | Same input with `"return_geometry":true` | `result_id`, `display_scope: oereb_parcel`, and one display feature. |
| Multiple layers | `{"layer_ids":["ch.swisstopo-vd.stand-oerebkataster","ch.swisstopo.amtliches-gebaeudeadressverzeichnis"],"longitude":7.451352,"latitude":46.927937,"lang":"en","limit":20}` | Records remain associated with their source layer. |
| Invalid coordinate | `{"layer_ids":["ch.test"],"longitude":500,"latitude":200}` | Explicit WGS84 validation error. |
| Unknown reference | `{"layer_ids":["ch.test"],"location_ref":"address:missing"}` | Explicit instruction to geocode first. |

---

## 5. `search_locations`

**What it does:** Resolves named Swiss administrative and locality areas for accurate clipping and map focus.

### Input

| Field | Type | Required | Description |
|---|---:|:---:|---|
| `query` | string | Yes | Canton, district, commune, locality, or Switzerland. |
| `lang` | language code | No | Request language. |
| `top_n` | integer | No | Maximum results; default is 10. |

### Output

```json
{
  "places": [
    {
      "name": "Zug",
      "kind": "kanton",
      "canton": "ZG",
      "bbox": [8.394846, 47.08103, 8.701169, 47.248375],
      "similarity": 1.0
    }
  ]
}
```

### Customer query

> Find the canton of Zug and show me which administrative level was selected.

### Configuration acceptance tests

| Case | Direct MCP input | Expected check |
|---|---|---|
| Canton | `{"query":"Zug","lang":"en","top_n":10}` | Results expose the canton and other same-name levels separately. |
| Accent normalization | `{"query":"Geneve","lang":"fr","top_n":5}` | Resolves `Genève`. |
| Commune | `{"query":"Köniz","lang":"de","top_n":5}` | Commune result with canton `BE`. |
| Locality | `{"query":"Wengen","lang":"en","top_n":5}` | Resolves a locality even though it is not a commune. |
| Country | `{"query":"Switzerland","lang":"en","top_n":3}` | Resolves the Swiss national boundary. |
| Ambiguous hierarchy | `{"query":"Zürich","lang":"de","top_n":10}` | Canton, district, commune, and locality are not silently merged. |
| Unknown place | `{"query":"Atlantis","lang":"en","top_n":5}` | Empty result with a no-match note. |

---

## 6. `display_division`

**What it does:** Publishes a selected administrative boundary as a personalized, clickable GeoParquet layer.

### Input

| Field | Type | Required | Description |
|---|---:|:---:|---|
| `name` | string | Yes | Exact name returned by `search_locations`. |
| `kind` | string | No | One of `land`, `kanton`, `bezirk`, `gemeinde`, or `ortschaft`; use it to disambiguate repeated names. |

### Output

```json
{
  "layer": {
    "id": "division-kanton-Zug",
    "name": "Zug",
    "format": "parquet",
    "url": "https://…",
    "geometry_type": "Polygon",
    "feature_count": 1,
    "bbox": [8.394846, 47.08103, 8.701169, 47.248375],
    "attribution": "swisstopo / geo.admin.ch · swissBOUNDARIES3D"
  }
}
```

### Customer query

> Show the boundary of the canton of Zug on the map.

### Configuration acceptance tests

| Case | Direct MCP input | Expected check |
|---|---|---|
| Country | `{"name":"Schweiz","kind":"land"}` | One national boundary layer. |
| Canton | `{"name":"Zug","kind":"kanton"}` | One canton boundary, not the commune of Zug. |
| District | `{"name":"Bern-Mittelland","kind":"bezirk"}` | District boundary when present in the official division index. |
| Commune | `{"name":"Köniz","kind":"gemeinde"}` | Commune boundary. |
| Locality | `{"name":"Wengen","kind":"ortschaft"}` | Locality/postcode geometry. |
| Missing name | `{"name":"Atlantis","kind":"gemeinde"}` | Explicit not-found error. |

---

## 7. `filter_features`

**What it does:** Fetches complete queryable features and clips them either to a true named boundary or to the current rectangular map view.

### Input

| Field | Type | Required | Description |
|---|---:|:---:|---|
| `layer_id` | string | Yes | Queryable layer returned by `search_layers`. |
| `place` | string | Conditional | Exact place name returned by `search_locations`; preferred. |
| `place_kind` | string | No | Administrative level used to disambiguate `place`. |
| `bbox` | four-number array | Conditional | WGS84 `[minLon,minLat,maxLon,maxLat]`; use for an unnamed map view. |
| `lang` | language code | No | Feature language. |
| `contains` | string | No | Compatibility text search across feature values. |
| `filters` | object array | No | Safe filters with `field`, `operator`, and `value`. |
| `time` | string | No | Requested dataset timestamp/vintage. |

Supported filter operators: `equals`, `not_equals`, `contains`, `starts_with`, `greater_than`, `greater_or_equal`, `less_than`, and `less_or_equal`.

### Output

```json
{
  "result_id": "fs_…",
  "layer_id": "ch.swisstopo.swissboundaries3d-gemeinde-flaeche.fill",
  "feature_count": 11,
  "geometry_type": "polygon",
  "bbox": [8.394846, 47.08103, 8.701169, 47.248375],
  "attributes": { "gemname": ["Baar", "Cham", "…"] },
  "clipped_to": "kanton Zug"
}
```

### Customer query

> Find every municipality inside the true boundary of the canton of Zug, not merely inside its bounding rectangle.

### Configuration acceptance tests

| Case | Direct MCP input | Expected check |
|---|---|---|
| Named boundary | `{"layer_id":"ch.swisstopo.swissboundaries3d-gemeinde-flaeche.fill","place":"Zug","place_kind":"kanton","lang":"en"}` | Exactly 11 municipalities and `clipped_to: kanton Zug`. |
| Raw map bbox | `{"layer_id":"ch.swisstopo.swissboundaries3d-gemeinde-flaeche.fill","bbox":[8.394846,47.08103,8.701169,47.248375],"lang":"en"}` | Rectangular result may include neighboring cantons; it must not claim true canton clipping. |
| Text compatibility | Add `"contains":"Baar"` | Only records containing `Baar`. |
| Equality | Add `"filters":[{"field":"kanton","operator":"equals","value":"ZG"}]` | Only matching records. |
| Inequality | Use `not_equals` | Excludes the specified value. |
| String prefix | Use `starts_with` on a valid text field | Only prefix matches. |
| Numeric comparison | Use `greater_than`, `greater_or_equal`, `less_than`, and `less_or_equal` on a numeric field discovered with `describe_layer` | Correct numeric subset for each operator. |
| Time vintage | Add `"time":"2025"` to a time-enabled layer | Requests that official vintage rather than mixing years. |
| Invalid field | `"filters":[{"field":"does_not_exist","operator":"equals","value":"x"}]` | Explicit error listing available fields. |
| Raster layer | Use a `queryable:false` flood-warning layer | Semantic response says it cannot be queried; the agent should use `display_catalog_layer`. |
| No area | Omit both `place` and `bbox` | Explicit area-validation error. |
| Empty result | Valid layer and area with a filter that matches nothing | `feature_count: 0`, no invented `result_id`. |

---

## 8. `display_catalog_layer`

**What it does:** Creates a trusted reference to an existing official map layer without copying its tiles through the MCP or model.

### Input

| Field | Type | Required | Description |
|---|---:|:---:|---|
| `layer_id` | string | Yes | Official displayable layer ID. |
| `lang` | language code | No | Localized catalogue configuration. |
| `name` | string | No | User-facing localized name. |
| `opacity` | number | No | Requested map opacity, normally from 0 to 1. |
| `focus_bbox` | four-number array | No | WGS84 camera target after the user adds the layer. |

### Output

```json
{
  "catalog_layer": {
    "id": "ch.bafu.hydroweb-warnkarte_national",
    "name": "Flood warning map",
    "opacity": 0.7,
    "attribution": "swisstopo / geo.admin.ch"
  },
  "layer_type": "wmts",
  "focus_bbox": [6.770579, 45.858185, 8.478519, 46.654047]
}
```

### Customer query

> Make the current flood warning map available to add to the map, focused on Valais, at 70% opacity.

### Configuration acceptance tests

| Case | Direct MCP input | Expected check |
|---|---|---|
| WMTS | `{"layer_id":"ch.bafu.hydroweb-warnkarte_national","lang":"en","name":"Flood warning map","opacity":0.7,"focus_bbox":[6.770579,45.858185,8.478519,46.654047]}` | WMTS reference and Valais focus. |
| WMS | `{"layer_id":"ch.swisstopo-vd.stand-oerebkataster","lang":"de","name":"Verfügbarkeit des ÖREB-Katasters"}` | WMS catalogue reference. |
| GeoJSON delivery | Use a known official GeoJSON-configured layer | `layer_type: geojson`. |
| Fully transparent/opaque | Test `opacity:0` and `opacity:1` | Values are preserved in the reference. |
| No focus | Omit `focus_bbox` | Layer is offered without a forced camera target. |
| Unknown ID | `{"layer_id":"ch.invalid.does-not-exist","lang":"en"}` | Explicit official-layer validation error. |
| Non-renderable layer | Use a known layer whose delivery type is not WMS/WMTS/GeoJSON | Explicit cannot-render error. |

---

## 9. `analyze_features`

**What it does:** Computes deterministic figures over a server-cached result rather than asking the language model to estimate them.

### Input

| Field | Type | Required | Description |
|---|---:|:---:|---|
| `result_id` | string | Yes | Exact handle returned by `filter_features` or geometry-enabled `identify_at_point`. |
| `operation` | string | No | `summary`, `count`, `area`, `length`, `extent`, `group_by`, `numeric_statistics`, or `top_values`. |
| `field` | string | Conditional | Required for `group_by`, `numeric_statistics`, and `top_values`. |
| `metrics` | string array | No | Group metrics (`count`, `area`, `length`) or numeric metrics (`min`, `max`, `mean`, `sum`). |
| `limit` | integer | No | Maximum grouped/top-value rows, capped at 100. |

### Output

```json
{
  "result_id": "fs_…",
  "count": 11,
  "area_km2": 238.73,
  "length_km": 290.43,
  "bbox": [8.394846, 47.08103, 8.701169, 47.248375]
}
```

### Customer query

> For the municipalities fetched in canton Zug, calculate the count, total area, total boundary length, extent, and numeric area statistics.

### Configuration acceptance tests

First obtain a `result_id` by filtering the Zug municipality layer.

| Operation | Direct MCP input | Expected check |
|---|---|---|
| Summary | `{"result_id":"<id>","operation":"summary"}` | Count, area, length, and bbox. |
| Count | `{"result_id":"<id>","operation":"count"}` | Count only. |
| Area | `{"result_id":"<id>","operation":"area"}` | Total square kilometres. |
| Length | `{"result_id":"<id>","operation":"length"}` | Total kilometres. |
| Extent | `{"result_id":"<id>","operation":"extent"}` | WGS84 bbox. |
| Group count/area | `{"result_id":"<id>","operation":"group_by","field":"kanton","metrics":["count","area"],"limit":20}` | One `ZG` group with count and area. |
| Frequent values | `{"result_id":"<id>","operation":"top_values","field":"objektart_lookup","limit":5}` | Five or fewer values ordered by frequency. |
| Default numeric stats | `{"result_id":"<id>","operation":"numeric_statistics","field":"gemflaeche"}` | Numeric count, min, max, mean, and sum. |
| Selected numeric stats | Add `"metrics":["min","max"]` | Only the selected numeric metrics plus numeric count. |
| Missing field | Omit `field` for `group_by` | Explicit field-required error. |
| Non-numeric field | Request numeric statistics on a text field | Explicit no-numeric-values error. |
| Unknown result | `{"result_id":"fs_missing","operation":"summary"}` | Explicit unknown-result error. |
| Invalid operation | `{"result_id":"<id>","operation":"invented"}` | Explicit supported-operation error. |

---

## 10. `display_layer`

**What it does:** Publishes a cached point, parcel, boundary, or filtered feature set as a personalized GeoParquet result layer.

### Input

| Field | Type | Required | Description |
|---|---:|:---:|---|
| `result_id` | string | Yes | Exact handle returned by `geocode_location`, `filter_features`, or geometry-enabled `identify_at_point`. |
| `name` | string | Yes | Customer-facing layer name in the conversation language. |
| `fill_color` | string | No | Optional color hint such as `#4a90d9`. |
| `opacity` | number | No | Optional opacity hint. |

### Output

```json
{
  "layer": {
    "id": "fs_…",
    "name": "Municipalities of canton Zug",
    "format": "parquet",
    "url": "https://…/fs_….parquet",
    "geometry_type": "polygon",
    "feature_count": 11,
    "bbox": [8.394846, 47.08103, 8.701169, 47.248375],
    "attribution": "swisstopo / geo.admin.ch · ch.swisstopo.…",
    "style_hint": { "fill_color": "#4a90d9", "opacity": 0.6 }
  }
}
```

### Customer query

> Find all municipalities in canton Zug and prepare the personalized result for the map with a blue fill at 60% opacity.

### Configuration acceptance tests

| Case | Direct MCP input | Expected check |
|---|---|---|
| Geocoded point | `{"result_id":"<from geocode>","name":"Seftigenstrasse 264, Wabern"}` | One point feature and a personalized-result card. |
| ÖREB parcel | `{"result_id":"<from identify return_geometry=true>","name":"ÖREB parcel CH669746359158","fill_color":"#e84a5f","opacity":0.5}` | One parcel polygon, not the enclosing municipality. |
| Filtered polygons | `{"result_id":"<from Zug filter>","name":"Municipalities of canton Zug","fill_color":"#4a90d9","opacity":0.6}` | Eleven polygons and style hints. |
| No style | Omit color and opacity | Layer remains displayable with frontend defaults. |
| Unknown result | `{"result_id":"fs_missing","name":"Missing result"}` | Explicit unknown-result error. |

---

# Multi-tool customer acceptance workflows

These natural-language tests exercise the agent's planning and the connections between tools. Tool sequences are expectations, not instructions shown to the end user.

## Workflow A — Address coordinates and personalized marker

**Turn 1**

> Find the exact coordinates of Seftigenstrasse 264, 3084 Wabern.

**Turn 2**

> Show me on the map.

Expected tools:

```text
geocode_location
→ display_layer
```

Acceptance criteria:

- Match quality is `exact`.
- WGS84 is approximately `7.451352, 46.927937`.
- LV95 is approximately `2'600'968.69 / 1'197'426.89`.
- The second turn produces one personalized point layer.
- It does not substitute the nationwide Official Building and Address Register layer.

## Workflow B — Complete ÖREB extract and both map-layer types

> Locate Seftigenstrasse 264, 3084 Wabern; return the EGRID, official PDF extract, online extract, and responsible authority. Prepare the exact parcel result for the map and offer the official nationwide ÖREB availability layer separately.

Expected tools:

```text
geocode_location
→ search_layers
→ identify_at_point(return_geometry=true)
→ display_layer
→ display_catalog_layer
```

Acceptance criteria:

- EGRID is `CH669746359158`.
- Both `oereb_extract_pdf` and `oereb_extract_url` are present.
- Personalized result: one exact parcel polygon with **Show result on map**.
- Official result: `Verfügbarkeit des ÖREB-Katasters` with **Add map layer** and **Layer details**.
- The parcel must not be described as the municipality boundary.

## Workflow C — Flood layers in Valais

> For canton Valais, compare the current flood warning map, measurement-station danger levels, surface-runoff hazards, and Aquaprotect flood scenarios. Show the canton boundary and make every recommended official layer available to add to the map.

Expected tools:

```text
search_locations
→ search_layers
→ display_division
→ display_catalog_layer (one or more official layers)
```

Acceptance criteria:

- The subject search excludes the place name.
- Valais is resolved as a canton.
- A personalized canton boundary is produced.
- Official layer titles are clickable inline.
- Raster layers are not sent to `filter_features`.

## Workflow D — Municipality analysis in Zug

> Find every municipality in canton Zug. Tell me the exact count, total area, total boundary length, minimum/maximum/average municipality area, and show both the municipalities and canton boundary on the map.

Expected tools:

```text
search_locations
→ search_layers
→ filter_features(place="Zug", place_kind="kanton")
→ analyze_features(summary)
→ analyze_features(numeric_statistics)
→ display_division
→ display_layer
```

Acceptance criteria:

- The result is clipped to the real canton boundary.
- Municipality count is 11.
- Figures come from `analyze_features`, not model estimation.
- The feature result and canton boundary appear as separate personalized layers.

## Workflow E — Structured attribute filtering

> In canton Zug, find municipality features whose canton field equals ZG and whose official area is greater than 1,000 hectares. Count them, calculate their combined area, and show the filtered result on the map.

Expected tools:

```text
search_locations
→ search_layers
→ describe_layer
→ filter_features(structured filters)
→ analyze_features
→ display_layer
```

Acceptance criteria:

- Field names are taken from the schema.
- The MCP uses structured operators, never a raw SQL-like expression.
- The count and area describe the filtered subset only.

## Workflow F — Current map-view analysis

First pan and zoom the map to a small area, then ask:

> In the area currently visible on the map, find all municipality features, count them, calculate their total area, and show the result as a personalized layer.

Expected tools:

```text
search_layers
→ filter_features(bbox from map_context)
→ analyze_features
→ display_layer
```

Acceptance criteria:

- The current WGS84 map bbox is used because the user explicitly referred to the visible area.
- The answer clearly describes a rectangular map-view result, not a named administrative boundary.

## Workflow G — Multilingual flood discovery

Run the same intent in the five supported interface languages:

```text
Show me flood hazards in Valais.
Zeige mir Hochwassergefahren im Wallis.
Montre-moi les dangers de crues en Valais.
Mostrami i pericoli di piena in Vallese.
Mussa ma ils privels d'inundaziun en il Vallais.
```

Acceptance criteria:

- Every answer uses the requested language.
- Relevant official flood layers are found in every language.
- Localized display names do not break their stable `ch.*` layer IDs.
- Inline official-layer controls remain available.

## Workflow H — Graceful no-match and validation behavior

> Find an official Swiss geodata layer containing historical Bitcoin prices for Atlantis and show it on the map.

Acceptance criteria:

- The agent does not invent a layer or Swiss place.
- The response explains that no matching official Swiss geodata was found.
- No generated or official map layer is emitted.
