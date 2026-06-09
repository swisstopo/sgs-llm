import { API3_BASE_URL } from '../config';
import type { AppLanguage } from '../i18n/i18n';

/**
 * Layer metadata from the Swisstopo `layersConfig` endpoint. WMTS tile
 * parameters (format, timestamp), labels, and attribution must always be
 * resolved from here — they vary per layer and are never hardcoded.
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
  /** Tile image format for WMTS layers (`png` or `jpeg`). */
  format?: string;
  /** Available WMTS time dimensions, newest first. */
  timestamps?: string[];
  opacity?: number;
  /** Whether the layer supports identify (feature tooltips). */
  tooltip: boolean;
  hasLegend: boolean;
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
    });
  }
  return result;
}

/** Fetches the full layer catalog metadata in the given language. */
export async function fetchLayersConfig(
  lang: AppLanguage,
): Promise<globalThis.Map<string, LayerConfig>> {
  const response = await fetch(`${API3_BASE_URL}/api/MapServer/layersConfig?lang=${lang}`);
  if (!response.ok) {
    throw new Error(`layersConfig request failed: ${response.status}`);
  }
  return parseLayersConfig(await response.json());
}
