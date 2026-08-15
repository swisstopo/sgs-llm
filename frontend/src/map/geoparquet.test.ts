/// <reference types="node" />

import { readFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import * as hyparquet from 'hyparquet';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { decodeGeoParquet } from './geoparquet';

vi.mock('hyparquet', async (importOriginal) => {
  const actual = await importOriginal<typeof import('hyparquet')>();
  return {
    ...actual,
    parquetMetadataAsync: vi.fn(actual.parquetMetadataAsync),
    parquetReadObjects: vi.fn(actual.parquetReadObjects),
  };
});

const fixture = fileURLToPath(new URL('../../test-data/chat-layer.parquet', import.meta.url));

describe('decodeGeoParquet', () => {
  afterEach(() => vi.clearAllMocks());

  it('decodes real GeoParquet geometry, ids, types, nulls, and reserved properties', async () => {
    const bytes = await readFile(fixture);
    const features = await decodeGeoParquet(
      bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength),
    );

    expect(features).toHaveLength(5);
    expect(features.map((feature) => feature.geometry.type)).toEqual([
      'Point',
      'LineString',
      'Polygon',
      'MultiPoint',
      'MultiPolygon',
    ]);
    expect(features[0]).toEqual({
      type: 'Feature',
      id: '7',
      geometry: { type: 'Point', coordinates: [7.44, 46.95] },
      properties: {
        name: 'Bern',
        count: 2,
        open: true,
        nullable: null,
        geometry: 'property geometry',
        feature_id: null,
        meta: null,
        tags: null,
      },
    });
    expect(features[1]?.properties.tags).toBe('["road","walk"]');
    expect(features[4]?.properties.meta).toBe('{"a":1,"b":2}');
  });

  it('rejects a file without GeoParquet metadata', async () => {
    const bytes = new TextEncoder().encode('not parquet').buffer;
    await expect(decodeGeoParquet(bytes)).rejects.toThrow(/GeoParquet|Parquet/i);
  });

  it('rejects more than 100,000 rows before decoding them', async () => {
    const bytes = await readFile(fixture);
    const buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
    const metadata = await hyparquet.parquetMetadataAsync(buffer);
    vi.mocked(hyparquet.parquetMetadataAsync).mockResolvedValueOnce({
      ...metadata,
      num_rows: 100_001n,
    });
    const reader = vi.mocked(hyparquet.parquetReadObjects);

    await expect(decodeGeoParquet(buffer)).rejects.toThrow(
      'GeoParquet contains more than 100,000 features',
    );
    expect(reader).not.toHaveBeenCalled();
  });

  it.each([
    ['bad-wkb', /WKB/],
    ['bad-crs', /CRS84/],
  ])('rejects invalid %s metadata', async (name, expected) => {
    const path = fileURLToPath(
      new URL(`../../test-data/chat-layer-${name}.parquet`, import.meta.url),
    );
    const bytes = await readFile(path);

    await expect(
      decodeGeoParquet(bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength)),
    ).rejects.toThrow(expected);
  });
});
