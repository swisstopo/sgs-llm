// @vitest-environment jsdom

import { afterEach, describe, expect, it, vi } from 'vitest';
import type Tile from 'ol/Tile';
import { get as getProjection } from 'ol/proj';
import type Projection from 'ol/proj/Projection';
import type RenderFeature from 'ol/render/Feature';
import type { LayerSpec } from '../protocol/v1';
import { expandTileTemplate, isLayerExpired, MvtTileSource } from './mvtLayer';

const MVT_BODY = Uint8Array.from(
  atob('Gj4KA3NncxIRCAcSBAAAAQEYASIFCYAggCAaBG5hbWUaBGtpbmQiBwoFT2x0ZW4iCgoIYnVpbGRpbmcogCB4Ag=='),
  (character) => character.charCodeAt(0),
);

const SPEC: LayerSpec = {
  id: 'buildings',
  name: 'Buildings',
  format: 'mvt',
  url: '/data/tiles/token/{z}/{x}/{y}.mvt',
  dispose_url: '/data/layers/token',
  geometry_type: 'polygon',
  min_zoom: 0,
  max_zoom: 16,
};

type FetchFeatures = (
  z: number,
  x: number,
  y: number,
  extent: number[],
  projection: Projection,
  signal: AbortSignal,
) => Promise<RenderFeature[]>;

function fetchFeatures(source: MvtTileSource, signal = new AbortController().signal) {
  const projection = getProjection('EPSG:3857');
  if (!projection) throw new Error('EPSG:3857 is unavailable');
  return (source as unknown as { fetchFeatures: FetchFeatures }).fetchFeatures(
    12,
    2138,
    1434,
    [0, 0, 4096, 4096],
    projection,
    signal,
  );
}

function queuedTile(source: MvtTileSource, index: number) {
  const tile = { setLoader: vi.fn(), setFeatures: vi.fn(), setState: vi.fn() };
  source.getTileLoadFunction()(tile as unknown as Tile, `sgs-mvt://12/${2138 + index}/1434`);
  const loader = tile.setLoader.mock.calls[0]?.[0] as
    | ((extent: number[], resolution: number, projection: Projection) => void)
    | undefined;
  const projection = getProjection('EPSG:3857');
  if (!loader || !projection) throw new Error('tile loader was not installed');
  loader([0, 0, 4096, 4096], 1, projection);
  return tile;
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('MVT tile source', () => {
  it('expands all coordinates and recognizes expired capabilities', () => {
    expect(expandTileTemplate('/tiles/{z}/{x}/{y}.mvt', 12, 2138, 1434)).toBe(
      '/tiles/12/2138/1434.mvt',
    );
    expect(isLayerExpired({ ...SPEC, url_expires_at: '2000-01-01T00:00:00Z' })).toBe(true);
    expect(isLayerExpired(SPEC)).toBe(false);
  });

  it('decodes a real MVT response with its native feature id and properties', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(MVT_BODY));
    vi.stubGlobal('fetch', fetchMock);

    const features = await fetchFeatures(new MvtTileSource(SPEC));

    expect(features).toHaveLength(1);
    expect(features[0]?.getId()).toBe(7);
    expect(features[0]?.get('name')).toBe('Olten');
    expect(fetchMock).toHaveBeenCalledWith(
      '/data/tiles/token/12/2138/1434.mvt',
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it('treats backend 204 as an empty tile', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 204 })));
    await expect(fetchFeatures(new MvtTileSource(SPEC))).resolves.toEqual([]);
  });

  it('retries a temporary 503 and then decodes the tile', async () => {
    vi.useFakeTimers();
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 503 }))
      .mockResolvedValueOnce(new Response(MVT_BODY));
    vi.stubGlobal('fetch', fetchMock);

    const pending = fetchFeatures(new MvtTileSource(SPEC));
    await vi.runAllTimersAsync();

    await expect(pending).resolves.toHaveLength(1);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('reports a 410 capability as expired', async () => {
    const expired = vi.fn();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 410 })));

    await expect(fetchFeatures(new MvtTileSource(SPEC, { onExpired: expired }))).rejects.toThrow(
      'expired',
    );
    expect(expired).toHaveBeenCalledOnce();
  });

  it('applies one six-request limit across all generated layers', async () => {
    vi.useFakeTimers();
    const signals: AbortSignal[] = [];
    const fetchMock = vi.fn((_url: string, init?: RequestInit) => {
      const signal = init?.signal as AbortSignal;
      signals.push(signal);
      return new Promise<Response>((_resolve, reject) => {
        signal.addEventListener('abort', () => reject(new DOMException('aborted', 'AbortError')), {
          once: true,
        });
      });
    });
    vi.stubGlobal('fetch', fetchMock);
    const first = new MvtTileSource(SPEC);
    const second = new MvtTileSource({ ...SPEC, id: 'roads' });
    const tiles = Array.from({ length: 8 }, (_, index) =>
      queuedTile(index % 2 === 0 ? first : second, index),
    );

    await vi.advanceTimersByTimeAsync(200);
    expect(fetchMock).toHaveBeenCalledTimes(6);

    first.abortPending();
    second.abortPending();
    await vi.runAllTimersAsync();
    expect(signals.every((signal) => signal.aborted)).toBe(true);
    expect(fetchMock).toHaveBeenCalledTimes(6);
    expect(tiles.every((tile) => tile.setFeatures.mock.calls.at(-1)?.[0]?.length === 0)).toBe(true);
  });
});
