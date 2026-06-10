import proj4 from 'proj4';
import { register } from 'ol/proj/proj4';

/** Swiss LV95 (EPSG:2056), used for the coordinate readout. */
const EPSG_2056 =
  '+proj=somerc +lat_0=46.9524055555556 +lon_0=7.43958333333333 +k_0=1 ' +
  '+x_0=2600000 +y_0=1200000 +ellps=bessel ' +
  '+towgs84=674.374,15.056,405.346,0,0,0,0 +units=m +no_defs +type=crs';

export function registerProjections(): void {
  proj4.defs('EPSG:2056', EPSG_2056);
  register(proj4);
}

/** Formats a Web Mercator coordinate as an LV95 string, e.g. "2'600'000, 1'200'000". */
export function formatLV95(coordinate3857: [number, number]): string {
  const [east, north] = proj4('EPSG:3857', 'EPSG:2056', coordinate3857);
  const fmt = (value: number) =>
    Math.round(value)
      .toString()
      .replace(/\B(?=(\d{3})+(?!\d))/g, "'");
  return `${fmt(east!)}, ${fmt(north!)}`;
}
