import { API3_BASE_URL } from '../config';
import type { AppLanguage } from '../i18n/i18n';

export interface IdentifyParams {
  /** Click coordinate in EPSG:3857. */
  coordinate: [number, number];
  /** Layer ids to query (identify-capable, visible layers). */
  layerIds: string[];
  /** Current map extent in EPSG:3857. */
  mapExtent: [number, number, number, number];
  /** Map viewport size in px. */
  size: [number, number];
  lang: AppLanguage;
  tolerance?: number;
}

export interface IdentifyFeature {
  layerBodId: string;
  layerName: string;
  featureId: string | number;
  label: string;
  /** GeoJSON geometry in EPSG:3857 (when returned). */
  geometry?: unknown;
}

/** Spatial identify on the Swisstopo MapServer (features at a click point). */
export async function identify(params: IdentifyParams): Promise<IdentifyFeature[]> {
  const query = new URLSearchParams({
    geometry: params.coordinate.map((n) => n.toFixed(2)).join(','),
    geometryType: 'esriGeometryPoint',
    sr: '3857',
    mapExtent: params.mapExtent.map((n) => n.toFixed(2)).join(','),
    imageDisplay: `${Math.round(params.size[0])},${Math.round(params.size[1])},96`,
    tolerance: String(params.tolerance ?? 10),
    layers: `all:${params.layerIds.join(',')}`,
    lang: params.lang,
    returnGeometry: 'true',
    geometryFormat: 'geojson',
  });
  const response = await fetch(`${API3_BASE_URL}/all/MapServer/identify?${query}`);
  if (!response.ok) {
    throw new Error(`identify request failed: ${response.status}`);
  }
  const data = (await response.json()) as { results?: Record<string, unknown>[] };
  return (data.results ?? [])
    .filter(
      (result) =>
        typeof result.layerBodId === 'string' &&
        (typeof result.featureId === 'string' || typeof result.featureId === 'number'),
    )
    .map((result) => {
      const properties = result.properties as Record<string, unknown> | undefined;
      const label =
        typeof properties?.label === 'string' && properties.label.length > 0
          ? properties.label
          : String(result.featureId);
      return {
        layerBodId: result.layerBodId as string,
        layerName: typeof result.layerName === 'string' ? result.layerName : '',
        featureId: result.featureId as string | number,
        label,
        geometry: result.geometry,
      };
    });
}

/** URL of the feature detail HTML fragment (rendered sandboxed). */
export function htmlPopupUrl(
  layerBodId: string,
  featureId: string | number,
  lang: AppLanguage,
): string {
  return `${API3_BASE_URL}/ech/MapServer/${encodeURIComponent(layerBodId)}/${encodeURIComponent(
    String(featureId),
  )}/htmlPopup?lang=${lang}&sr=3857`;
}
