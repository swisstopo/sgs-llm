/**
 * SGS LLM agent WebSocket protocol, version 1 (path `/ws/v1`).
 *
 * Canonical TypeScript definition of the contract between the frontend and
 * the agent backend. The normative, language-neutral description lives in
 * docs/protocol.md (+ JSON Schemas in docs/protocol/); keep them in sync.
 *
 * Compatibility rules: clients ignore unknown event types and unknown
 * fields. Exactly one `final` or `error` event concludes a user message,
 * always followed by `done`.
 */

export type ProtocolLang = 'de' | 'fr' | 'it' | 'en' | 'rm';
export type ModelPreference = 'primary' | 'secondary' | 'apertus';

export interface HistoryEntry {
  role: 'user' | 'assistant';
  content: string;
}

/** [minLon, minLat, maxLon, maxLat] in WGS84. */
export type ProtocolBBox = [number, number, number, number];

export interface MapContext {
  bbox: ProtocolBBox;
  active_layer_ids: string[];
}

export interface UserMessageEvent {
  type: 'user_message';
  /** Client-generated unique id, echoed as `message_id` in server events. */
  id: string;
  content: string;
  lang: ProtocolLang;
  /** Agent model routing: Claude primary, Mistral secondary, or self-hosted Apertus. */
  model: ModelPreference;
  history?: HistoryEntry[];
  map_context?: MapContext;
}

export interface CancelEvent {
  type: 'cancel';
  /** Id of the in-flight user message to cancel. */
  id: string;
}

export type ClientEvent = UserMessageEvent | CancelEvent;

export interface StyleHint {
  fill_color?: string;
  stroke_color?: string;
  stroke_width?: number;
  point_radius?: number;
  opacity?: number;
}

/** A data layer produced by the agent, fetched by the client from `url`. */
export interface LayerSpec {
  id: string;
  name: string;
  format: 'geojson' | 'parquet';
  url: string;
  geometry_type: 'point' | 'line' | 'polygon';
  feature_count?: number;
  bbox?: ProtocolBBox;
  attribution?: string;
  style_hint?: StyleHint;
}

/** An official geo.admin.ch layer resolved and tiled directly by the browser. */
export interface CatalogLayerRef {
  id: string;
  name?: string;
  opacity?: number;
  attribution?: string;
}

export interface IntermediateEvent {
  type: 'intermediate';
  message_id: string;
  step_id: string;
  status: 'started' | 'finished' | 'failed';
  /** Human-readable progress label, localized to the request language. */
  label: string;
  detail?: string;
}

export interface FinalEvent {
  type: 'final';
  message_id: string;
  content_markdown: string;
  layers?: LayerSpec[];
  catalog_layers?: CatalogLayerRef[];
  focus_bbox?: ProtocolBBox;
}

export type ErrorCode = 'internal' | 'timeout' | 'bad_request' | 'cancelled' | 'model_unavailable';

export interface ErrorEvent {
  type: 'error';
  message_id: string;
  code: ErrorCode;
  message: string;
}

export interface DoneEvent {
  type: 'done';
  message_id: string;
}

export type ServerEvent = IntermediateEvent | FinalEvent | ErrorEvent | DoneEvent;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function isBBox(value: unknown): value is ProtocolBBox {
  return Array.isArray(value) && value.length === 4 && value.every((n) => typeof n === 'number');
}

function isStyleHint(value: unknown): value is StyleHint {
  return isRecord(value);
}

export function isLayerSpec(value: unknown): value is LayerSpec {
  if (!isRecord(value)) {
    return false;
  }
  return (
    typeof value.id === 'string' &&
    typeof value.name === 'string' &&
    (value.format === 'geojson' || value.format === 'parquet') &&
    typeof value.url === 'string' &&
    (value.geometry_type === 'point' ||
      value.geometry_type === 'line' ||
      value.geometry_type === 'polygon') &&
    (value.feature_count === undefined || typeof value.feature_count === 'number') &&
    (value.bbox === undefined || isBBox(value.bbox)) &&
    (value.attribution === undefined || typeof value.attribution === 'string') &&
    (value.style_hint === undefined || isStyleHint(value.style_hint))
  );
}

export function isCatalogLayerRef(value: unknown): value is CatalogLayerRef {
  if (!isRecord(value) || typeof value.id !== 'string' || !/^ch\.[a-z0-9_.-]+$/.test(value.id)) {
    return false;
  }
  return (
    (value.name === undefined || typeof value.name === 'string') &&
    (value.opacity === undefined ||
      (typeof value.opacity === 'number' && value.opacity >= 0 && value.opacity <= 1)) &&
    (value.attribution === undefined || typeof value.attribution === 'string')
  );
}

/**
 * Parses a raw WebSocket frame into a known server event. Returns null for
 * malformed frames and unknown event types (forward compatibility).
 */
export function parseServerEvent(raw: string): ServerEvent | null {
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!isRecord(data) || typeof data.message_id !== 'string') {
    return null;
  }
  switch (data.type) {
    case 'intermediate':
      if (
        typeof data.step_id === 'string' &&
        (data.status === 'started' || data.status === 'finished' || data.status === 'failed') &&
        typeof data.label === 'string'
      ) {
        return {
          type: 'intermediate',
          message_id: data.message_id,
          step_id: data.step_id,
          status: data.status,
          label: data.label,
          detail: typeof data.detail === 'string' ? data.detail : undefined,
        };
      }
      return null;
    case 'final':
      if (typeof data.content_markdown === 'string') {
        const layers = Array.isArray(data.layers) ? data.layers.filter(isLayerSpec) : undefined;
        const catalogLayers = Array.isArray(data.catalog_layers)
          ? data.catalog_layers.filter(isCatalogLayerRef)
          : undefined;
        return {
          type: 'final',
          message_id: data.message_id,
          content_markdown: data.content_markdown,
          layers,
          catalog_layers: catalogLayers,
          focus_bbox: isBBox(data.focus_bbox) ? data.focus_bbox : undefined,
        };
      }
      return null;
    case 'error':
      if (typeof data.message === 'string') {
        const code: ErrorCode =
          data.code === 'timeout' ||
          data.code === 'bad_request' ||
          data.code === 'cancelled' ||
          data.code === 'model_unavailable'
            ? data.code
            : 'internal';
        return { type: 'error', message_id: data.message_id, code, message: data.message };
      }
      return null;
    case 'done':
      return { type: 'done', message_id: data.message_id };
    default:
      return null;
  }
}
