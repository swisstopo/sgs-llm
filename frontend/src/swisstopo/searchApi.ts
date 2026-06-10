import { API3_BASE_URL } from '../config';
import type { AppLanguage } from '../i18n/i18n';
import type { BBox } from '../services/MapService';
import { fetchJson } from './http';

/** SearchServer rejects more than 10 search words. */
const MAX_SEARCH_WORDS = 10;

/** API maxima (and defaults) per the SearchServer documentation. */
const MAX_LOCATION_LIMIT = 50;
const MAX_LAYER_LIMIT = 30;

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

export interface LayerSearchOptions {
  limit?: number;
  signal?: AbortSignal;
}

export interface LocationSearchOptions {
  limit?: number;
  signal?: AbortSignal;
}

/** Clamps the query to the API's 10-word maximum. */
export function truncateSearchText(text: string): string {
  return text.trim().split(/\s+/).slice(0, MAX_SEARCH_WORDS).join(' ');
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

async function searchRequest(
  params: URLSearchParams,
  signal?: AbortSignal,
): Promise<Record<string, unknown>[]> {
  const data = (await fetchJson(`${API3_BASE_URL}/api/SearchServer?${params}`, {
    signal,
  })) as SearchServerResponse;
  return (data.results ?? [])
    .map((result) => result.attrs)
    .filter(
      (attrs): attrs is Record<string, unknown> => typeof attrs === 'object' && attrs !== null,
    );
}

/** Full-catalog layer search (API maximum: 30 results). */
export async function searchLayers(
  query: string,
  lang: AppLanguage,
  options: LayerSearchOptions = {},
): Promise<LayerSearchResult[]> {
  const params = new URLSearchParams({
    type: 'layers',
    searchText: truncateSearchText(query),
    lang,
    limit: String(Math.min(options.limit ?? MAX_LAYER_LIMIT, MAX_LAYER_LIMIT)),
  });
  const attrs = await searchRequest(params, options.signal);
  return attrs
    .filter((a) => typeof a.layer === 'string' && typeof a.label === 'string')
    .map((a) => ({ layerId: a.layer as string, label: stripHtml(a.label as string) }));
}

/**
 * Location/geocoding search (API maximum: 50 results). Results are ranked by
 * the server. Coordinates are returned in WGS84 (`sr=4326`).
 */
export async function searchLocations(
  query: string,
  options: LocationSearchOptions = {},
): Promise<LocationSearchResult[]> {
  const params = new URLSearchParams({
    type: 'locations',
    searchText: truncateSearchText(query),
    sr: '4326',
    limit: String(Math.min(options.limit ?? MAX_LOCATION_LIMIT, MAX_LOCATION_LIMIT)),
  });
  const attrs = await searchRequest(params, options.signal);
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
