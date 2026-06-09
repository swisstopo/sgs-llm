# Layer catalog

Curated layer tree shown in the map catalog panel.

- `layertree.json5` — groups with multilingual labels; children are bare
  Swisstopo layer ids (`layerBodId`). Labels, tile format, timestamps, and
  attribution of each layer are resolved at runtime from the
  [layersConfig endpoint](https://api3.geo.admin.ch/rest/services/api/MapServer/layersConfig),
  so entries here never duplicate official metadata.
- `layers_wmts.json5` — optional per-layer presentation overrides
  (e.g. `defaultOpacity`).

To add a layer, find its id on <https://map.geo.admin.ch> (or via the
SearchServer API) and append it to a group. Layers must be available as WMTS
(`type: "wmts"` in layersConfig) to be displayable.

The declarative JSON5 catalog structure is adapted from
[swisstopo/swissgeol-viewer-suite](https://github.com/swisstopo/swissgeol-viewer-suite)
(BSD-3-Clause); the content is specific to this project.
