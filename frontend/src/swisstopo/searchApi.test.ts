import { afterEach, describe, expect, it, vi } from 'vitest';
import { parseBox2d, searchLayers, searchLocations, stripHtml } from './searchApi';

describe('stripHtml', () => {
  it('removes highlight markup', () => {
    expect(stripHtml('<b>Bern (BE)</b>')).toBe('Bern (BE)');
    expect(stripHtml('plain')).toBe('plain');
  });
});

describe('parseBox2d', () => {
  it('parses a BOX string into [minLon, minLat, maxLon, maxLat]', () => {
    expect(parseBox2d('BOX(7.294133 46.918995,7.495609 46.990139)')).toEqual([
      7.294133, 46.918995, 7.495609, 46.990139,
    ]);
  });

  it('returns undefined for malformed input', () => {
    expect(parseBox2d('BOX(broken)')).toBeUndefined();
    expect(parseBox2d('')).toBeUndefined();
  });
});

describe('search requests', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('maps layer results and strips markup', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            results: [
              { attrs: { layer: 'ch.bafu.waldreservate', label: '<b>Waldreservate</b>' } },
              { attrs: { label: 'missing layer id' } },
            ],
          }),
        ),
      ),
    );
    const results = await searchLayers('wald', 'de');
    expect(results).toEqual([{ layerId: 'ch.bafu.waldreservate', label: 'Waldreservate' }]);
  });

  it('maps location results with bbox', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            results: [
              {
                attrs: {
                  label: '<b>Bern (BE)</b>',
                  detail: 'bern be',
                  lon: 7.42,
                  lat: 46.95,
                  geom_st_box2d: 'BOX(7.29 46.91,7.49 46.99)',
                },
              },
            ],
          }),
        ),
      ),
    );
    const results = await searchLocations('bern');
    expect(results[0]).toMatchObject({
      label: 'Bern (BE)',
      lon: 7.42,
      lat: 46.95,
      bbox: [7.29, 46.91, 7.49, 46.99],
    });
  });

  it('throws on a failed response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 503 })));
    await expect(searchLocations('bern')).rejects.toThrow(/503/);
  });
});
