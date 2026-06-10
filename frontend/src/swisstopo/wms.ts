import { WMS_BASE_URL } from '../config';
import type { LayerConfig } from './layersConfigApi';

/** True when the layer can be displayed via WMS GetMap. */
export function isWmsDisplayable(config: LayerConfig): boolean {
  return config.type === 'wms' && typeof config.wmsLayers === 'string' && config.wmsLayers !== '';
}

/** GetMap endpoint (the layer's own wmsUrl, falling back to the default service). */
export function wmsUrl(config: LayerConfig): string {
  return config.wmsUrl ?? WMS_BASE_URL;
}

/**
 * Static GetMap params; OpenLayers adds VERSION/CRS/BBOX/WIDTH/HEIGHT and
 * TRANSPARENT itself. TIME is deliberately not sent for `timeEnabled`
 * layers — the server default applies.
 */
export function wmsParams(config: LayerConfig): { LAYERS: string; FORMAT: string } {
  return {
    LAYERS: config.wmsLayers ?? '',
    FORMAT: `image/${config.format ?? 'png'}`,
  };
}
