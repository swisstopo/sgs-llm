# Agent guide

## Choose the right concept

Use `search_datasets` for the **subject** and `search_divisions` for the **area**. For
“avalanche datasets in Valais,” search `avalanche hazards` as the dataset query and
`Valais` as the division query. Including the place in the dataset query reduces recall.
Then call `get_map_preview_links` with the selected dataset IDs and the chosen division's
complete bbox. Dataset-search links intentionally show all of Switzerland; the composed
preview is the link centred on the requested area. For an ordinary city/town request,
prefer `kind="gemeinde"` unless the user specifically asks for a district or locality.
When several datasets are selected, present every `individual_links` URL separately. The
`combined_link` is an optional convenience after the individual links, not a replacement.

Use `geocode_location` when the request names a precise address, cadastral parcel,
postcode, or point. It returns both WGS84 and LV95. Use `identify_at_point` only after
selecting a curated preset and/or one or more exact `ch.*` dataset IDs; it returns records
intersecting that coordinate without geometry or GeoJSON.

## Point-identification presets

| Preset | Resolved official dataset | Use it for |
| --- | --- | --- |
| `parcel` | `ch.swisstopo-vd.amtliche-vermessung` | Parcel number, EGRID, municipality/canton metadata, and cantonal geoportal links. |
| `oereb` | `ch.swisstopo-vd.stand-oerebkataster` | ÖREB/PLR availability, responsible authority, parcel reference, and official cantonal extract links. |
| `all_relevant` | Both datasets above | One lightweight cadastral and ÖREB exploration call. |

`dataset_ids` remains available for any queryable layer found through dataset search. A
preset and explicit IDs can be supplied together; the server resolves and deduplicates
the final layer list. An ÖREB identify response is an exploration aid. Open its official
cantonal PDF/web extract for the authoritative result.

## Temporal point identification

Some queryable datasets are historicised: the same real-world feature has one record per
published year. `identify_at_point` pins every time-enabled dataset to its own latest
published timestamp by default and reports the choice in `temporal_context`. Do not treat
an omitted `year` as an unfiltered historical query.

Layer configuration is read live on every identify or dataset-description call and is not
cached by the MCP. If Swisstopo publishes a new year, the next call sees it automatically;
the agent does not need to wait for a deployment or server restart.

For a historical question, pass the requested four-digit `year`. The server resolves it
to the dataset's exact published timestamp and returns `time_not_available` if that year
does not exist; it never silently substitutes another year. Call `describe_dataset` first
and choose from its normalized `available_years`; retain raw `timestamps` only when the
exact GeoAdmin representation matters. A `time_not_available` error repeats the complete
valid-year list in `error.details.available_years` so the agent can recover without
guessing. When several datasets have different latest timestamps, the server queries them
separately and merges the records. Historical `map_preview_url` and `map_feature_url`
values include the same year. State the returned `year_used` when answering a user with a
value that can change over time.

## Division hierarchy

The index uses source terminology so identifiers remain unambiguous:

| Kind | Meaning |
| --- | --- |
| `land` | Switzerland. |
| `kanton` | One of 26 cantons. |
| `bezirk` | District or equivalent intermediate division. |
| `gemeinde` | Commune/municipality. |
| `kommunanz` | Territory shared by communes. |
| `kantonsgebiet` | Special canton territory represented in the commune source, commonly a large lake. |
| `ortschaft` | Official locality/postcode area below commune level. |

Names repeat. “Zürich” is a canton, district, commune, and locality; keep `kind` and
`division_ref` when explaining which one was selected. Locality records may group several
postcode polygons into one name. Their returned bbox encloses the group.

## Dataset capability

- `queryable: true` means `identify_at_point` can usually return feature attributes.
- `queryable: false` generally means raster/image content. It may still be displayable in
  a map client, but this search server does not render or return map geometry.
- `displayable: true` describes the current geo.admin.ch map service, not an instruction
  to mutate a user's map.
- Always call `describe_dataset` before naming fields, timestamps, downloads, or legal
  status. Do not infer fields from another related dataset.
- Dataset-search and description `map_preview_url` values use the nationwide view. For a
  named area, use `get_map_preview_links` and open its centred URL instead.

## Coordinates

- Bounding boxes: `[west, south, east, north]`, WGS84 (`EPSG:4326`).
- WGS84 point input: `{"longitude": ..., "latitude": ..., "crs": "EPSG:4326"}`.
- LV95 point input: `{"easting": ..., "northing": ..., "crs": "EPSG:2056"}`.

The geo.admin.ch SearchServer has historical `x` and `y` fields whose axis meaning changes
with the requested projection. This server intentionally replaces them with explicit
names.

Every geocode and identify response includes a `map_preview_url`. The server converts its
WGS84 point to the LV95 center required by the official map viewer, adds a marker, and
enables the resolved identify layers. Individual identify records can also include a
`map_feature_url`.

`get_map_preview_links` performs the same safe conversion for a division bbox, chooses an
area-appropriate zoom, and omits the point marker. It returns a separate centred URL for
each dataset and, when more than one is selected, an optional combined link.

## Suggested smoke calls

After starting HTTP mode, use an MCP client or Inspector to run:

```json
{"name":"search_datasets","arguments":{"query":"avalanche hazards","language":"en","limit":5}}
```

```json
{"name":"search_divisions","arguments":{"query":"Wallis","kinds":["kanton"],"limit":5}}
```

```json
{"name":"get_map_preview_links","arguments":{"dataset_ids":["ch.bfs.gebaeude_wohnungs_register"],"focus_bbox":[7.874858,47.311028,7.929085,47.368924],"language":"en"}}
```

```json
{"name":"geocode_location","arguments":{"query":"Seftigenstrasse 264, 3084 Wabern","origins":["address"],"language":"en","limit":1}}
```

```json
{"name":"describe_dataset","arguments":{"dataset_id":"ch.swisstopo-vd.stand-oerebkataster","language":"en"}}
```

```json
{"name":"identify_at_point","arguments":{"point":{"longitude":7.451352,"latitude":46.927937,"crs":"EPSG:4326"},"preset":"all_relevant","language":"en"}}
```

Historical example:

```json
{"name":"identify_at_point","arguments":{"point":{"longitude":6.96974,"latitude":46.31642,"crs":"EPSG:4326"},"dataset_ids":["ch.swisstopo.swissboundaries3d-gemeinde-flaeche.fill"],"year":2015,"language":"en"}}
```

The geocode result should be approximately longitude `7.451352`, latitude `46.927937`,
LV95 easting `2600968.7`, northing `1197427.0`. Values can change slightly when the
official source is updated.
