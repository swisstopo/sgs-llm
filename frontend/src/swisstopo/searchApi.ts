import { API3_BASE_URL } from '../config';
import type { AppLanguage } from '../i18n/i18n';
import type { BBox } from '../services/MapService';

export interface LayerSearchResult {
  layerId: string;
  label: string;
}

export interface LocationSearchResult {
  label: string;
  detail: string;
  lon: number;
  lat: number;
  bbox?: BBox;
}

/** SearchServer labels embed `<b>` highlights; the UI renders plain text. */
export function stripHtml(value: string): string {
  return value.replace(/<[^>]*>/g, '');
}

/** Parses `geom_st_box2d` values like `BOX(7.29 46.91,7.49 46.99)`. */
export function parseBox2d(value: string): BBox | undefined {
  const match = /^BOX\(([\d.-]+) ([\d.-]+),([\d.-]+) ([\d.-]+)\)$/.exec(value);
  if (!match) {
    return undefined;
  }
  const [minX, minY, maxX, maxY] = [match[1], match[2], match[3], match[4]].map(Number);
  if ([minX, minY, maxX, maxY].some((n) => n === undefined || Number.isNaN(n))) {
    return undefined;
  }
  return [minX!, minY!, maxX!, maxY!];
}

interface SearchServerResponse {
  results?: { attrs?: Record<string, unknown> }[];
}

async function searchRequest(params: URLSearchParams): Promise<Record<string, unknown>[]> {
  const response = await fetch(`${API3_BASE_URL}/api/SearchServer?${params}`);
  if (!response.ok) {
    throw new Error(`SearchServer request failed: ${response.status}`);
  }
  const data = (await response.json()) as SearchServerResponse;
  return (data.results ?? [])
    .map((result) => result.attrs)
    .filter(
      (attrs): attrs is Record<string, unknown> => typeof attrs === 'object' && attrs !== null,
    );
}

/** Full-catalog layer search (max 30 results, per the API). */
export async function searchLayers(query: string, lang: AppLanguage): Promise<LayerSearchResult[]> {
  const attrs = await searchRequest(
    new URLSearchParams({ type: 'layers', searchText: query, lang }),
  );
  return attrs
    .filter((a) => typeof a.layer === 'string' && typeof a.label === 'string')
    .map((a) => ({ layerId: a.layer as string, label: stripHtml(a.label as string) }));
}

/** Location/geocoding search in WGS84 (max 50 results, per the API). */
export async function searchLocations(query: string): Promise<LocationSearchResult[]> {
  const attrs = await searchRequest(
    new URLSearchParams({ type: 'locations', searchText: query, sr: '4326' }),
  );
  return attrs
    .filter(
      (a) => typeof a.label === 'string' && typeof a.lon === 'number' && typeof a.lat === 'number',
    )
    .map((a) => ({
      label: stripHtml(a.label as string),
      detail: typeof a.detail === 'string' ? a.detail : '',
      lon: a.lon as number,
      lat: a.lat as number,
      bbox: typeof a.geom_st_box2d === 'string' ? parseBox2d(a.geom_st_box2d) : undefined,
    }));
}
