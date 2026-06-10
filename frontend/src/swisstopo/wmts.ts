import { WMTS_BASE_URL } from '../config';
import type { LayerConfig } from './layersConfigApi';

/** True when the layer can be displayed as WMTS tiles. */
export function isWmtsDisplayable(config: LayerConfig): boolean {
  return config.type === 'wmts';
}

/**
 * Builds the XYZ tile URL template for a Swisstopo WMTS layer in Web
 * Mercator, using the layer's own format and newest timestamp.
 */
export function wmtsTileUrl(config: LayerConfig): string {
  const timestamp = config.timestamps?.[0] ?? 'current';
  const format = config.format ?? 'png';
  return `${WMTS_BASE_URL}/${config.id}/default/${timestamp}/3857/{z}/{x}/{y}.${format}`;
}

/** OpenLayers attribution string (label, optionally linked). */
export function layerAttribution(config: LayerConfig): string {
  if (config.attributionUrl) {
    return `<a href="${config.attributionUrl}" target="_blank" rel="noopener">© ${config.attribution}</a>`;
  }
  return `© ${config.attribution}`;
}
