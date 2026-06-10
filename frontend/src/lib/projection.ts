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

/** [minLon, minLat, maxLon, maxLat] / [minE, minN, maxE, maxN]. */
type Box = [number, number, number, number];

export function lonLatToLV95(lonLat: [number, number]): [number, number] {
  return proj4('EPSG:4326', 'EPSG:2056', lonLat) as [number, number];
}

export function lv95ToLonLat(eastNorth: [number, number]): [number, number] {
  return proj4('EPSG:2056', 'EPSG:4326', eastNorth) as [number, number];
}

/** Converts a WGS84 bbox to LV95 (corner-wise; fine at Swiss extents). */
export function bboxToLV95(bbox4326: Box): Box {
  const [minE, minN] = lonLatToLV95([bbox4326[0], bbox4326[1]]);
  const [maxE, maxN] = lonLatToLV95([bbox4326[2], bbox4326[3]]);
  return [minE, minN, maxE, maxN];
}

/** Converts an LV95 bbox to WGS84 (corner-wise). */
export function bboxLV95To4326(bbox2056: Box): Box {
  const [minLon, minLat] = lv95ToLonLat([bbox2056[0], bbox2056[1]]);
  const [maxLon, maxLat] = lv95ToLonLat([bbox2056[2], bbox2056[3]]);
  return [minLon, minLat, maxLon, maxLat];
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
