import type { LayerConfig } from './layersConfigApi';
import { isWmtsDisplayable } from './wmts';
import { isWmsDisplayable } from './wms';

/** True when the layer can be displayed as a GeoJSON vector layer. */
export function isGeoJsonDisplayable(config: LayerConfig): boolean {
  return config.type === 'geojson' && typeof config.geojsonUrl === 'string';
}

/** True when the app can put this official layer on the map. */
export function isDisplayable(config: LayerConfig): boolean {
  return isWmtsDisplayable(config) || isWmsDisplayable(config) || isGeoJsonDisplayable(config);
}

/** OpenLayers attribution string (label, optionally linked). */
export function layerAttribution(config: LayerConfig): string {
  if (config.attributionUrl) {
    return `<a href="${config.attributionUrl}" target="_blank" rel="noopener">© ${config.attribution}</a>`;
  }
  return `© ${config.attribution}`;
}
