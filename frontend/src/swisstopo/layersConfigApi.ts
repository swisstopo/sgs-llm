import { API3_BASE_URL } from '../config';
import type { AppLanguage } from '../i18n/i18n';
import { fetchJson } from './http';

/**
 * Layer metadata from the Swisstopo `layersConfig` endpoint. Service
 * parameters (tile format, timestamps, WMS/GeoJSON endpoints), labels, and
 * attribution must always be resolved from here — they vary per layer and
 * are never hardcoded.
 */
export interface LayerConfig {
  /** Layer identifier (`layerBodId`), e.g. `ch.swisstopo.pixelkarte-grau`. */
  id: string;
  /** Service type, e.g. `wmts`, `wms`, `aggregate`, `geojson`. */
  type: string;
  label: string;
  attribution: string;
  attributionUrl?: string;
  /** True for layers intended as basemaps. */
  background: boolean;
  /** Image format: WMTS tile extension or WMS FORMAT (`png` → `image/png`). */
  format?: string;
  /** Available WMTS time dimensions, newest first. */
  timestamps?: string[];
  opacity?: number;
  /** Whether the layer supports identify (feature tooltips). */
  tooltip: boolean;
  hasLegend: boolean;
  /** WMS GetMap endpoint for `wms` layers, e.g. `https://wms.geo.admin.ch`. */
  wmsUrl?: string;
  /** WMS LAYERS parameter; may be a comma-separated list. */
  wmsLayers?: string;
  /** True when the WMS layer must be requested as one untiled image. */
  singleTile?: boolean;
  /** Tile gutter in px for tiled WMS requests (avoids symbol clipping at tile edges). */
  gutter?: number;
  /** GeoJSON data URL for `geojson` layers (already language-resolved). */
  geojsonUrl?: string;
  /** Geoadmin vector style JSON URL (may be protocol-relative, `//api3...`). */
  styleUrl?: string;
  /** Re-fetch interval in ms for live `geojson` layers (e.g. rain radar). */
  updateDelay?: number;
  /** True when the layer has a server-side time dimension (TIME is not sent; the server default applies). */
  timeEnabled?: boolean;
}

export function parseLayersConfig(raw: unknown): globalThis.Map<string, LayerConfig> {
  const result = new globalThis.Map<string, LayerConfig>();
  if (typeof raw !== 'object' || raw === null) {
    return result;
  }
  for (const [id, value] of Object.entries(raw)) {
    if (typeof value !== 'object' || value === null) {
      continue;
    }
    const entry = value as Record<string, unknown>;
    if (typeof entry.type !== 'string' || typeof entry.label !== 'string') {
      continue;
    }
    result.set(id, {
      id,
      type: entry.type,
      label: entry.label,
      attribution: typeof entry.attribution === 'string' ? entry.attribution : '',
      attributionUrl: typeof entry.attributionUrl === 'string' ? entry.attributionUrl : undefined,
      background: entry.background === true,
      format: typeof entry.format === 'string' ? entry.format : undefined,
      timestamps: Array.isArray(entry.timestamps)
        ? entry.timestamps.filter((t): t is string => typeof t === 'string')
        : undefined,
      opacity: typeof entry.opacity === 'number' ? entry.opacity : undefined,
      tooltip: entry.tooltip === true,
      hasLegend: entry.hasLegend === true,
      wmsUrl: typeof entry.wmsUrl === 'string' ? entry.wmsUrl : undefined,
      wmsLayers: typeof entry.wmsLayers === 'string' ? entry.wmsLayers : undefined,
      singleTile: entry.singleTile === true,
      gutter: typeof entry.gutter === 'number' ? entry.gutter : undefined,
      geojsonUrl: typeof entry.geojsonUrl === 'string' ? entry.geojsonUrl : undefined,
      styleUrl: typeof entry.styleUrl === 'string' ? entry.styleUrl : undefined,
      updateDelay: typeof entry.updateDelay === 'number' ? entry.updateDelay : undefined,
      timeEnabled: entry.timeEnabled === true,
    });
  }
  return result;
}

/** Fetches the full layer catalog metadata in the given language (~1 MB, cached by the caller per language). */
export async function fetchLayersConfig(
  lang: AppLanguage,
): Promise<globalThis.Map<string, LayerConfig>> {
  return parseLayersConfig(
    await fetchJson(`${API3_BASE_URL}/api/MapServer/layersConfig?lang=${lang}`),
  );
}
