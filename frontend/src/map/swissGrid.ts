import WMTSTileGrid from 'ol/tilegrid/WMTS';

/**
 * Swisstopo WMTS tile grid for Swiss LV95 (EPSG:2056), from
 * https://wmts.geo.admin.ch/EPSG/2056/1.0.0/WMTSCapabilities.xml.
 * The grid extent is fully covered by map data, so the basemap renders as a
 * clean rectangle around Switzerland (as on map.geo.admin.ch / swissgeo).
 */

/** Resolutions in m/px for zoom levels 0–28. */
export const LV95_RESOLUTIONS = [
  4000, 3750, 3500, 3250, 3000, 2750, 2500, 2250, 2000, 1750, 1500, 1250, 1000, 750, 650, 500, 250,
  100, 50, 20, 10, 5, 2.5, 2, 1.5, 1, 0.5, 0.25, 0.1,
];

/**
 * View zoom ladder (matches map.geo.admin.ch): zoom 0 = 650 m/px, the
 * generalized national-map style with the surrounding countries, down to
 * 0.25 m/px. Keeping the view snapped to these levels means tiles always
 * render 1:1 — between-level resolutions would pick the next-finer level
 * and show the much denser label style when zoomed out.
 */
export const LV95_VIEW_RESOLUTIONS = LV95_RESOLUTIONS.filter(
  (resolution) => resolution <= 650 && resolution >= 0.25,
);

/** Top-left corner of the tile matrix. */
export const LV95_ORIGIN: [number, number] = [2420000, 1350000];

/** Full extent of the tile matrix, [minX, minY, maxX, maxY]. */
export const LV95_EXTENT: [number, number, number, number] = [2420000, 1030000, 2900000, 1350000];

/** Tile grid shared by all swisstopo WMTS layers (basemaps and overlays). */
export function lv95TileGrid(): WMTSTileGrid {
  return new WMTSTileGrid({
    origin: LV95_ORIGIN,
    resolutions: LV95_RESOLUTIONS,
    extent: LV95_EXTENT,
    matrixIds: LV95_RESOLUTIONS.map((_, z) => String(z)),
  });
}
