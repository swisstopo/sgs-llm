/**
 * Turning a vector feature's properties into something a popup can show.
 *
 * This is only for features whose geometry is already in the browser - the agent's data
 * layers and official geojson layers. Raster overlays (WMTS/WMS) have no client-side
 * geometry, so they keep going through the identify API instead (swisstopo/identifyApi).
 */

/**
 * Keys tried in order when naming a feature. Swisstopo's own vector layers use `label`
 * and `name`; the German/French variants cover the geojson layers that skip them.
 */
const LABEL_KEYS = [
  'label',
  'name',
  'title',
  'bezeichnung',
  'designation',
  'gemname',
  'ortschaftsname',
  'kanton',
];

/**
 * Dropped from the table: plumbing that repeats the geometry the user is already looking
 * at. Everything else is kept, including computed fields - `compute` writes its area and
 * length results into the feature properties, and those are the whole point of asking.
 */
const HIDDEN_KEYS = new Set(['geometry', 'geom', 'the_geom', 'bbox']);

function isHiddenKey(key: string): boolean {
  const normalized = key.toLowerCase();
  return (
    HIDDEN_KEYS.has(normalized) || normalized === '__feature_id' || normalized.startsWith('__sgs_')
  );
}

/** Rows shown before truncating. A popup is a glance, not a data export. */
export const MAX_PROPERTY_ROWS = 12;

type Properties = Record<string, unknown>;

/** Human-readable name for a feature, falling back to its id and then a generic label. */
export function featureLabel(properties: Properties, fallback: string): string {
  for (const key of LABEL_KEYS) {
    const value = properties[key];
    if (typeof value === 'string' && value.trim().length > 0) {
      return value.trim();
    }
  }
  // No conventional label key: take the first non-empty string property rather than
  // showing a bare id, which tells the user nothing about what they clicked.
  for (const [key, value] of Object.entries(properties)) {
    if (!isHiddenKey(key) && typeof value === 'string' && value.trim()) {
      return value.trim();
    }
  }
  return fallback;
}

/** Formats one property value. Floats are rounded - raw areas are 10 digits of noise. */
export function formatValue(value: unknown): string {
  if (typeof value === 'number') {
    return Number.isInteger(value) ? String(value) : value.toFixed(2);
  }
  if (typeof value === 'boolean') {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value.map(formatValue).join(', ');
  }
  if (value !== null && typeof value === 'object') {
    return JSON.stringify(value);
  }
  return String(value);
}

/**
 * Property rows for the popup: geometry plumbing and empty values removed, capped at
 * MAX_PROPERTY_ROWS. Insertion order is kept, so the producer's field order survives.
 */
export function displayProperties(properties: Properties): [string, string][] {
  const rows: [string, string][] = [];
  for (const [key, value] of Object.entries(properties)) {
    if (isHiddenKey(key)) {
      continue;
    }
    if (value === null || value === undefined || value === '') {
      continue;
    }
    rows.push([key, formatValue(value)]);
    if (rows.length >= MAX_PROPERTY_ROWS) {
      break;
    }
  }
  return rows;
}
