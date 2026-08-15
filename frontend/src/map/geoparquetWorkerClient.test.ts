import { afterEach, describe, expect, it, vi } from 'vitest';
import type { DecodedFeature } from './geoparquet';
import { loadGeoParquet, type GeoParquetWorker } from './geoparquetWorkerClient';

class FakeWorker implements GeoParquetWorker {
  onmessage: ((event: MessageEvent) => void) | null = null;
  onerror: ((event: ErrorEvent) => void) | null = null;
  readonly postMessage = vi.fn();
  readonly terminate = vi.fn();

  message(data: unknown): void {
    this.onmessage?.({ data } as MessageEvent);
  }

  error(message: string): void {
    this.onerror?.({ message } as ErrorEvent);
  }
}

const feature: DecodedFeature = {
  type: 'Feature',
  id: '1',
  geometry: { type: 'Point', coordinates: [7.44, 46.95] },
  properties: { name: 'Bern' },
};

describe('loadGeoParquet', () => {
  const fetchMock = vi.fn();

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('delivers chunks in order and terminates after done', async () => {
    const buffer = new ArrayBuffer(8);
    fetchMock.mockResolvedValue(new Response(buffer));
    vi.stubGlobal('fetch', fetchMock);
    const worker = new FakeWorker();
    const chunks: DecodedFeature[][] = [];

    const loading = loadGeoParquet('https://data.test/a.parquet', (chunk) => chunks.push(chunk), {
      createWorker: () => worker,
    });
    await vi.waitFor(() => expect(worker.postMessage).toHaveBeenCalledTimes(1));
    expect(worker.postMessage).toHaveBeenCalledWith(buffer, [buffer]);
    worker.message({ type: 'chunk', features: [feature] });
    worker.message({ type: 'chunk', features: [{ ...feature, id: '2' }] });
    worker.message({ type: 'done' });

    await expect(loading).resolves.toBeUndefined();
    expect(chunks.flat().map((item) => item.id)).toEqual(['1', '2']);
    expect(worker.terminate).toHaveBeenCalledTimes(1);
  });

  it('rejects an HTTP failure without creating a worker', async () => {
    fetchMock.mockResolvedValue(new Response('unavailable', { status: 503 }));
    vi.stubGlobal('fetch', fetchMock);
    const createWorker = vi.fn();

    await expect(
      loadGeoParquet('https://data.test/a.parquet', vi.fn(), { createWorker }),
    ).rejects.toThrow('503');
    expect(createWorker).not.toHaveBeenCalled();
  });

  it('rejects a worker-declared decode failure and terminates it', async () => {
    fetchMock.mockResolvedValue(new Response(new ArrayBuffer(8)));
    vi.stubGlobal('fetch', fetchMock);
    const worker = new FakeWorker();
    const loading = loadGeoParquet('https://data.test/a.parquet', vi.fn(), {
      createWorker: () => worker,
    });
    await vi.waitFor(() => expect(worker.postMessage).toHaveBeenCalled());

    worker.message({ type: 'error', message: 'GeoParquet must use CRS84' });

    await expect(loading).rejects.toThrow('GeoParquet must use CRS84');
    expect(worker.terminate).toHaveBeenCalledTimes(1);
  });

  it('rejects and terminates when the layer consumer rejects a chunk', async () => {
    fetchMock.mockResolvedValue(new Response(new ArrayBuffer(8)));
    vi.stubGlobal('fetch', fetchMock);
    const worker = new FakeWorker();
    const loading = loadGeoParquet(
      'https://data.test/a.parquet',
      () => {
        throw new Error('OpenLayers rejected geometry');
      },
      { createWorker: () => worker },
    );
    await vi.waitFor(() => expect(worker.postMessage).toHaveBeenCalled());

    worker.message({ type: 'chunk', features: [feature] });

    await expect(loading).rejects.toThrow('OpenLayers rejected geometry');
    expect(worker.terminate).toHaveBeenCalledTimes(1);
  });

  it('rejects a browser worker error and terminates it', async () => {
    fetchMock.mockResolvedValue(new Response(new ArrayBuffer(8)));
    vi.stubGlobal('fetch', fetchMock);
    const worker = new FakeWorker();
    const loading = loadGeoParquet('https://data.test/a.parquet', vi.fn(), {
      createWorker: () => worker,
    });
    await vi.waitFor(() => expect(worker.postMessage).toHaveBeenCalled());

    worker.error('worker crashed');

    await expect(loading).rejects.toThrow('worker crashed');
    expect(worker.terminate).toHaveBeenCalledTimes(1);
  });

  it('aborts fetch and terminates a started worker while ignoring late messages', async () => {
    fetchMock.mockResolvedValue(new Response(new ArrayBuffer(8)));
    vi.stubGlobal('fetch', fetchMock);
    const worker = new FakeWorker();
    const controller = new AbortController();
    const onChunk = vi.fn();
    const loading = loadGeoParquet('https://data.test/a.parquet', onChunk, {
      createWorker: () => worker,
      signal: controller.signal,
    });
    await vi.waitFor(() => expect(worker.postMessage).toHaveBeenCalled());

    controller.abort();
    worker.message({ type: 'chunk', features: [feature] });
    worker.message({ type: 'done' });

    await expect(loading).rejects.toMatchObject({ name: 'AbortError' });
    expect(onChunk).not.toHaveBeenCalled();
    expect(worker.terminate).toHaveBeenCalledTimes(1);
  });
});
