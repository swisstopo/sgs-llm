import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  parseBox2d,
  searchLayers,
  searchLocations,
  stripHtml,
  truncateSearchText,
} from './searchApi';

describe('truncateSearchText', () => {
  it('keeps short queries unchanged', () => {
    expect(truncateSearchText('  Bern Hauptbahnhof ')).toBe('Bern Hauptbahnhof');
  });

  it('clamps to the 10-word API maximum', () => {
    const words = Array.from({ length: 14 }, (_, i) => `w${i}`).join(' ');
    expect(truncateSearchText(words).split(' ')).toHaveLength(10);
  });
});

describe('stripHtml', () => {
  it('removes highlight markup', () => {
    expect(stripHtml('<b>Bern (BE)</b>')).toBe('Bern (BE)');
    expect(stripHtml('plain')).toBe('plain');
  });
});

describe('parseBox2d', () => {
  it('parses a BOX string into [minX, minY, maxX, maxY]', () => {
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

  function stubFetch(results: unknown[]): ReturnType<typeof vi.fn> {
    // A fresh Response per call: a body can only be consumed once.
    const fetchMock = vi
      .fn()
      .mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ results }))));
    vi.stubGlobal('fetch', fetchMock);
    return fetchMock;
  }

  it('passes an explicit layer limit and truncates the query', async () => {
    const fetchMock = stubFetch([
      { attrs: { layer: 'ch.bafu.waldreservate', label: '<b>Waldreservate</b>' } },
      { attrs: { label: 'missing layer id' } },
    ]);
    const longQuery = Array.from({ length: 12 }, (_, i) => `wald${i}`).join(' ');
    const results = await searchLayers(longQuery, 'de', { limit: 10 });

    const url = new URL(fetchMock.mock.calls[0]![0] as string);
    expect(url.searchParams.get('limit')).toBe('10');
    expect(url.searchParams.get('searchText')!.split(' ')).toHaveLength(10);
    expect(results).toEqual([{ layerId: 'ch.bafu.waldreservate', label: 'Waldreservate' }]);
  });

  it('clamps limits to the API maxima', async () => {
    const fetchMock = stubFetch([]);
    await searchLayers('wald', 'de', { limit: 99 });
    await searchLocations('bern', { limit: 99 });
    expect(new URL(fetchMock.mock.calls[0]![0] as string).searchParams.get('limit')).toBe('30');
    expect(new URL(fetchMock.mock.calls[1]![0] as string).searchParams.get('limit')).toBe('50');
  });

  it('maps location results with bbox in plain 4326 mode', async () => {
    const fetchMock = stubFetch([
      {
        attrs: {
          label: '<b>Bern (BE)</b>',
          detail: 'bern be',
          lon: 7.42,
          lat: 46.95,
          geom_st_box2d: 'BOX(7.29 46.91,7.49 46.99)',
        },
      },
    ]);
    const results = await searchLocations('bern', { limit: 5 });
    const url = new URL(fetchMock.mock.calls[0]![0] as string);
    expect(url.searchParams.get('sr')).toBe('4326');
    expect(url.searchParams.has('bbox')).toBe(false);
    expect(results[0]).toMatchObject({
      label: 'Bern (BE)',
      lon: 7.42,
      lat: 46.95,
      bbox: [7.29, 46.91, 7.49, 46.99],
    });
  });

  it('forwards the abort signal', async () => {
    const fetchMock = vi.fn(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener('abort', () =>
            reject(new DOMException('Aborted', 'AbortError')),
          );
        }),
    );
    vi.stubGlobal('fetch', fetchMock);
    const controller = new AbortController();
    const pending = searchLocations('bern', { signal: controller.signal });
    controller.abort();
    await expect(pending).rejects.toThrow(/abort/i);
  });

  it('throws on a failed response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('', { status: 503 })));
    await expect(searchLocations('bern')).rejects.toThrow(/503/);
  });
});
