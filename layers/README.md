# Layer overrides

The map catalog is the official Swisstopo **CatalogServer** (topics and layer
trees fetched live), so this directory does not maintain its own layer tree.

- `layers_wmts.json5` — optional per-layer **presentation overrides** applied
  when a layer is added to the map. Only deviations from the Swisstopo
  `layersConfig` defaults belong here (currently `defaultOpacity` for a couple
  of raster layers that are clearer when slightly transparent).

Everything else about a layer — its label, tile format, timestamps, and
attribution — is resolved at runtime from the
[layersConfig endpoint](https://api3.geo.admin.ch/rest/services/api/MapServer/layersConfig),
so entries here never duplicate official metadata. Layer ids can be found on
<https://map.geo.admin.ch> or via the SearchServer / CatalogServer APIs.
