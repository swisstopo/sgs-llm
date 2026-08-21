# Agent guide

## Choose the right concept

Use `search_datasets` for the **subject** and `search_divisions` for the **area**. For
“avalanche datasets in Valais,” search `avalanche hazards` as the dataset query and
`Valais` as the division query. Including the place in the dataset query reduces recall.
Then call `create_map_preview` with the selected dataset IDs and the chosen division's
complete bbox. Dataset-search links intentionally show all of Switzerland; the composed
preview is the link centred on the requested area. For an ordinary city/town request,
prefer `kind="gemeinde"` unless the user specifically asks for a district or locality.
When several datasets are selected, present every `dataset_previews` URL separately. The
combined URL is an optional convenience after the individual links, not a replacement.

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
  named area, use `create_map_preview` and open its centred URL instead.

## Coordinates

- Bounding boxes: `[west, south, east, north]`, WGS84 (`EPSG:4326`).
- Point inputs: `longitude`, then `latitude`, WGS84.
- Swiss grid output: `easting`, then `northing`, LV95 (`EPSG:2056`).

The geo.admin.ch SearchServer has historical `x` and `y` fields whose axis meaning changes
with the requested projection. This server intentionally replaces them with explicit
names.

Every geocode and identify response includes a `map_preview_url`. The server converts its
WGS84 point to the LV95 center required by the official map viewer, adds a marker, and
enables the resolved identify layers. Individual identify records can also include a
`map_feature_url`.

`create_map_preview` performs the same safe conversion for a division bbox, chooses an
area-appropriate zoom, and omits the point marker. It returns a separate centred preview
for each dataset and, when more than one is selected, an optional combined preview.

## Suggested smoke calls

After starting HTTP mode, use an MCP client or Inspector to run:

```json
{"name":"search_datasets","arguments":{"query":"avalanche hazards","language":"en","limit":5}}
```

```json
{"name":"search_divisions","arguments":{"query":"Wallis","kinds":["kanton"],"limit":5}}
```

```json
{"name":"create_map_preview","arguments":{"dataset_ids":["ch.bfs.gebaeude_wohnungs_register"],"focus_bbox":[7.874858,47.311028,7.929085,47.368924],"language":"en"}}
```

```json
{"name":"geocode_location","arguments":{"query":"Seftigenstrasse 264, 3084 Wabern","origins":["address"],"language":"en","limit":1}}
```

```json
{"name":"describe_dataset","arguments":{"dataset_id":"ch.swisstopo-vd.stand-oerebkataster","language":"en"}}
```

```json
{"name":"identify_at_point","arguments":{"longitude":7.451352,"latitude":46.927937,"preset":"all_relevant","language":"en"}}
```

The geocode result should be approximately longitude `7.451352`, latitude `46.927937`,
LV95 easting `2600968.7`, northing `1197427.0`. Values can change slightly when the
official source is updated.
