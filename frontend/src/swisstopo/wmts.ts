import { WMTS_BASE_URL } from '../config';
import type { LayerConfig } from './layersConfigApi';

/** True when the layer can be displayed as WMTS tiles. */
export function isWmtsDisplayable(config: LayerConfig): boolean {
  return config.type === 'wmts';
}

/**
 * Builds the XYZ tile URL template for a Swisstopo WMTS layer in Swiss LV95
 * (EPSG:2056), using the layer's own format and newest timestamp. Sources
 * must pair it with the LV95 tile grid (see map/swissGrid.ts).
 */
export function wmtsTileUrl(config: LayerConfig): string {
  const timestamp = config.timestamps?.[0] ?? 'current';
  const format = config.format ?? 'png';
  return `${WMTS_BASE_URL}/${config.id}/default/${timestamp}/2056/{z}/{x}/{y}.${format}`;
}
