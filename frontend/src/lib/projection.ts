import proj4 from 'proj4';
import { register } from 'ol/proj/proj4';
import { get as getProjection, transform } from 'ol/proj';
import { containsCoordinate } from 'ol/extent';
import { LV95_EXTENT } from '../map/swissGrid';

/** Swiss LV95 (EPSG:2056), the map's display projection. */
const EPSG_2056 =
  '+proj=somerc +lat_0=46.9524055555556 +lon_0=7.43958333333333 +k_0=1 ' +
  '+x_0=2600000 +y_0=1200000 +ellps=bessel ' +
  '+towgs84=674.374,15.056,405.346,0,0,0,0 +units=m +no_defs +type=crs';

/** Legacy LV03 (EPSG:21781), occasionally declared by data.geo.admin.ch GeoJSON files. */
const EPSG_21781 =
  '+proj=somerc +lat_0=46.9524055555556 +lon_0=7.43958333333333 +k_0=1 ' +
  '+x_0=600000 +y_0=200000 +ellps=bessel ' +
  '+towgs84=674.374,15.056,405.346,0,0,0,0 +units=m +no_defs +type=crs';

export function registerProjections(): void {
  proj4.defs('EPSG:2056', EPSG_2056);
  proj4.defs('EPSG:21781', EPSG_21781);
  register(proj4);
  // The tile-grid extent lets OL derive default grids/resolutions (e.g. for WMS sources).
  getProjection('EPSG:2056')?.setExtent(LV95_EXTENT);
}

/** WGS84 lon/lat to LV95, or undefined when outside the LV95 map extent. */
export function lonLatToLV95InBounds(lonLat: [number, number]): [number, number] | undefined {
  const coordinate = transform(lonLat, 'EPSG:4326', 'EPSG:2056') as [number, number];
  return containsCoordinate(LV95_EXTENT, coordinate) ? coordinate : undefined;
}

/** Formats an LV95 map coordinate, e.g. "2'600'000, 1'200'000". */
export function formatLV95(coordinate2056: [number, number]): string {
  const fmt = (value: number) =>
    Math.round(value)
      .toString()
      .replace(/\B(?=(\d{3})+(?!\d))/g, "'");
  return `${fmt(coordinate2056[0])}, ${fmt(coordinate2056[1])}`;
}
