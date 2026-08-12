import { parquetMetadataAsync, parquetReadObjects } from 'hyparquet';
import { compressors } from 'hyparquet-compressors';

export interface GeoJsonGeometry {
  type: string;
  coordinates?: unknown;
  geometries?: GeoJsonGeometry[];
}

export interface DecodedFeature {
  type: 'Feature';
  id?: string;
  geometry: GeoJsonGeometry;
  properties: Record<string, unknown>;
}

interface GeoMetadata {
  version?: unknown;
  primary_column?: unknown;
  columns?: Record<string, { encoding?: unknown; crs?: { id?: unknown } }>;
}

function metadataValue(
  metadata: { key_value_metadata?: Array<{ key: string; value?: string }> },
  key: string,
): string | undefined {
  return metadata.key_value_metadata?.find((entry) => entry.key === key)?.value;
}

function parseObject(value: string | undefined, label: string): Record<string, unknown> {
  if (!value) {
    throw new Error(`GeoParquet is missing ${label} metadata`);
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(value);
  } catch {
    throw new Error(`GeoParquet has invalid ${label} metadata`);
  }
  if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
    throw new Error(`GeoParquet has invalid ${label} metadata`);
  }
  return parsed as Record<string, unknown>;
}

function validateGeoMetadata(value: Record<string, unknown>): string {
  const geo = value as GeoMetadata;
  if (geo.version !== '1.1.0' || typeof geo.primary_column !== 'string') {
    throw new Error('GeoParquet must use version 1.1.0 with a primary geometry column');
  }
  const column = geo.columns?.[geo.primary_column];
  if (!column || column.encoding !== 'WKB') {
    throw new Error('GeoParquet primary geometry must use WKB encoding');
  }
  const id = column.crs?.id;
  if (
    typeof id !== 'object' ||
    id === null ||
    (id as { authority?: unknown }).authority !== 'OGC' ||
    (id as { code?: unknown }).code !== 'CRS84'
  ) {
    throw new Error('GeoParquet geometry must use OGC:CRS84');
  }
  return geo.primary_column;
}

function normalizeScalar(value: unknown): unknown {
  if (typeof value !== 'bigint') {
    return value;
  }
  const number = Number(value);
  return Number.isSafeInteger(number) ? number : value.toString();
}

function isGeometry(value: unknown): value is GeoJsonGeometry {
  return (
    typeof value === 'object' &&
    value !== null &&
    typeof (value as { type?: unknown }).type === 'string'
  );
}

/** Decode the strict GeoParquet contract emitted by geosearch. */
export async function decodeGeoParquet(buffer: ArrayBuffer): Promise<DecodedFeature[]> {
  let metadata;
  try {
    metadata = await parquetMetadataAsync(buffer);
  } catch (error) {
    throw new Error('Could not read Parquet metadata', { cause: error });
  }
  const geometryColumn = validateGeoMetadata(parseObject(metadataValue(metadata, 'geo'), 'geo'));
  const propertyColumns = parseObject(
    metadataValue(metadata, 'sgs:property_columns'),
    'sgs:property_columns',
  );
  const rows = await parquetReadObjects({ file: buffer, compressors });

  return rows.map((row, index) => {
    const geometry = row[geometryColumn];
    if (!isGeometry(geometry)) {
      throw new Error(`GeoParquet row ${index} has no decoded geometry`);
    }
    const properties: Record<string, unknown> = {};
    for (const [original, physical] of Object.entries(propertyColumns)) {
      if (typeof physical !== 'string' || !(physical in row)) {
        throw new Error(`GeoParquet property mapping for ${original} is invalid`);
      }
      properties[original] = normalizeScalar(row[physical]);
    }
    const feature: DecodedFeature = { type: 'Feature', geometry, properties };
    const id = row.feature_id;
    if (id !== null && id !== undefined) {
      feature.id = String(id);
    }
    return feature;
  });
}
