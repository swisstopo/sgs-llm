import { describe, expect, it } from 'vitest';
import { isLayerSpec, parseServerEvent } from './v1';

describe('parseServerEvent', () => {
  it('parses intermediate events', () => {
    const event = parseServerEvent(
      JSON.stringify({
        type: 'intermediate',
        message_id: 'm1',
        step_id: 's1',
        status: 'started',
        label: 'Searching layers …',
      }),
    );
    expect(event).toMatchObject({ type: 'intermediate', step_id: 's1', status: 'started' });
  });

  it('parses final events and filters invalid layers', () => {
    const event = parseServerEvent(
      JSON.stringify({
        type: 'final',
        message_id: 'm1',
        content_markdown: '## Result',
        layers: [
          {
            id: 'l1',
            name: 'Flood zones',
            format: 'geojson',
            url: 'http://localhost:8787/data/flood.geojson',
            geometry_type: 'polygon',
            bbox: [7.0, 46.0, 8.0, 46.5],
          },
          { id: 'broken' },
        ],
      }),
    );
    expect(event?.type).toBe('final');
    if (event?.type === 'final') {
      expect(event.layers).toHaveLength(1);
      expect(event.layers?.[0]?.name).toBe('Flood zones');
    }
  });

  it('normalizes unknown error codes to internal', () => {
    const event = parseServerEvent(
      JSON.stringify({ type: 'error', message_id: 'm1', code: 'weird', message: 'boom' }),
    );
    expect(event).toMatchObject({ type: 'error', code: 'internal' });
  });

  it('parses done events', () => {
    expect(parseServerEvent(JSON.stringify({ type: 'done', message_id: 'm1' }))).toEqual({
      type: 'done',
      message_id: 'm1',
    });
  });

  it('returns null for unknown types, missing ids, and malformed JSON', () => {
    expect(parseServerEvent(JSON.stringify({ type: 'fancy_new', message_id: 'm1' }))).toBeNull();
    expect(parseServerEvent(JSON.stringify({ type: 'done' }))).toBeNull();
    expect(parseServerEvent('{not json')).toBeNull();
  });

  it('tolerates unknown extra fields', () => {
    const event = parseServerEvent(
      JSON.stringify({ type: 'done', message_id: 'm1', some_future_field: 42 }),
    );
    expect(event?.type).toBe('done');
  });
});

describe('isLayerSpec', () => {
  const validMvt = {
    id: 'roads',
    name: 'Roads',
    format: 'mvt',
    url: '/data/tiles/token/{z}/{x}/{y}.mvt',
    dispose_url: '/data/layers/token',
    url_expires_at: '2026-08-11T10:00:00Z',
    geometry_type: 'line',
    min_zoom: 0,
    max_zoom: 16,
  } as const;

  it('accepts GeoJSON without generated-tile metadata', () => {
    expect(
      isLayerSpec({
        id: 'l1',
        name: 'n',
        format: 'geojson',
        url: 'https://example.com/x.geojson',
        geometry_type: 'point',
      }),
    ).toBe(true);
  });

  it('accepts MVT with disposal, expiry, and zoom metadata', () => {
    expect(isLayerSpec(validMvt)).toBe(true);
  });

  it.each([
    { min_zoom: 17, max_zoom: 16 },
    { min_zoom: -1 },
    { max_zoom: 25 },
    { url: '/data/tiles/token/all.mvt' },
    { fallback_url: '/data/tiles/token/{z}/{x}/{y}.mvt' },
    { url_expires_at: 'not-a-date' },
  ])('rejects invalid MVT cross-fields: $url', (override) => {
    expect(isLayerSpec({ ...validMvt, ...override })).toBe(false);
  });

  it.each(['render_format', 'render_url', 'render_expires_at', 'parquet'])(
    'rejects the removed %s field',
    (removedField) => {
      const value =
        removedField === 'parquet'
          ? { ...validMvt, format: 'parquet' }
          : {
              ...validMvt,
              [removedField]: undefined,
            };
      expect(isLayerSpec(value)).toBe(false);
    },
  );

  it('rejects MVT-only fields on GeoJSON', () => {
    expect(
      isLayerSpec({
        id: 'l1',
        name: 'GeoJSON',
        format: 'geojson',
        url: '/data/layer.geojson',
        dispose_url: '/data/layers/token',
        geometry_type: 'polygon',
      }),
    ).toBe(false);
  });

  it('rejects wrong formats and geometry types', () => {
    expect(
      isLayerSpec({ id: 'l1', name: 'n', format: 'csv', url: 'u', geometry_type: 'point' }),
    ).toBe(false);
    expect(
      isLayerSpec({ id: 'l1', name: 'n', format: 'geojson', url: 'u', geometry_type: 'volume' }),
    ).toBe(false);
  });
});
