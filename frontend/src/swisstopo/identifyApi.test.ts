import { afterEach, describe, expect, it, vi } from 'vitest';
import { htmlPopupUrl, identify } from './identifyApi';

describe('identify', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('builds the request and maps geojson results', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(
        JSON.stringify({
          results: [
            {
              type: 'Feature',
              layerBodId: 'ch.bav.haltestellen-oev',
              layerName: 'öV-Haltestellen',
              featureId: 8519406,
              properties: { label: 'Bern, Zytglogge' },
              geometry: { type: 'Point', coordinates: [2601031, 1199680] },
            },
            { broken: true },
          ],
        }),
      ),
    );
    vi.stubGlobal('fetch', fetchMock);

    const results = await identify({
      coordinate: [2601031, 1199680],
      layerIds: ['ch.bav.haltestellen-oev', 'ch.bafu.waldreservate'],
      mapExtent: [2560000, 1170000, 2640000, 1230000],
      size: [1200, 600],
      lang: 'de',
    });

    const url = new URL(fetchMock.mock.calls[0]![0] as string);
    expect(url.pathname).toContain('/all/MapServer/identify');
    expect(url.searchParams.get('layers')).toBe(
      'all:ch.bav.haltestellen-oev,ch.bafu.waldreservate',
    );
    expect(url.searchParams.get('sr')).toBe('2056');
    expect(url.searchParams.get('tolerance')).toBe('10');
    expect(url.searchParams.get('geometryFormat')).toBe('geojson');
    expect(url.searchParams.get('limit')).toBe('200');

    expect(results).toHaveLength(1);
    expect(results[0]).toMatchObject({
      layerBodId: 'ch.bav.haltestellen-oev',
      label: 'Bern, Zytglogge',
      featureId: 8519406,
    });
  });

  it('falls back to the feature id as label', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            results: [{ layerBodId: 'x', layerName: 'X', featureId: 42, properties: {} }],
          }),
        ),
      ),
    );
    const results = await identify({
      coordinate: [0, 0],
      layerIds: ['x'],
      mapExtent: [0, 0, 1, 1],
      size: [100, 100],
      lang: 'fr',
    });
    expect(results[0]?.label).toBe('42');
  });
});

describe('htmlPopupUrl', () => {
  it('builds the popup URL', () => {
    expect(htmlPopupUrl('ch.bav.haltestellen-oev', 8519406, 'de')).toBe(
      'https://api3.geo.admin.ch/rest/services/ech/MapServer/ch.bav.haltestellen-oev/8519406/htmlPopup?lang=de&sr=2056',
    );
  });
});
