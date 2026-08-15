import type { DecodedFeature } from './geoparquet';

export interface GeoParquetWorker {
  onmessage: ((event: MessageEvent) => void) | null;
  onerror: ((event: ErrorEvent) => void) | null;
  postMessage(message: ArrayBuffer, transfer: Transferable[]): void;
  terminate(): void;
}

interface LoadOptions {
  signal?: AbortSignal;
  createWorker?: () => GeoParquetWorker;
}

type WorkerMessage =
  | { type: 'chunk'; features: DecodedFeature[] }
  | { type: 'done' }
  | { type: 'error'; message: string };

function defaultWorker(): GeoParquetWorker {
  return new Worker(new URL('./geoparquet.worker.ts', import.meta.url), { type: 'module' });
}

function abortError(): DOMException {
  return new DOMException('GeoParquet layer load was aborted', 'AbortError');
}

/** Fetch one GeoParquet artifact and own its decode worker through completion. */
export async function loadGeoParquet(
  url: string,
  onChunk: (features: DecodedFeature[]) => void,
  options: LoadOptions = {},
): Promise<void> {
  const { signal } = options;
  if (signal?.aborted) {
    throw abortError();
  }
  const response = await fetch(url, { signal });
  if (!response.ok) {
    throw new Error(`data layer request failed: ${response.status}`);
  }
  const buffer = await response.arrayBuffer();
  if (signal?.aborted) {
    throw abortError();
  }
  const worker = (options.createWorker ?? defaultWorker)();

  await new Promise<void>((resolve, reject) => {
    let settled = false;
    const finish = (error?: Error) => {
      if (settled) {
        return;
      }
      settled = true;
      signal?.removeEventListener('abort', onAbort);
      worker.onmessage = null;
      worker.onerror = null;
      worker.terminate();
      if (error) {
        reject(error);
      } else {
        resolve();
      }
    };
    const onAbort = () => finish(abortError());

    signal?.addEventListener('abort', onAbort, { once: true });
    worker.onmessage = (event: MessageEvent<WorkerMessage>) => {
      if (settled) {
        return;
      }
      const message = event.data;
      if (message.type === 'chunk') {
        try {
          onChunk(message.features);
        } catch (error) {
          finish(error instanceof Error ? error : new Error('GeoParquet chunk was rejected'));
        }
      } else if (message.type === 'done') {
        finish();
      } else if (message.type === 'error') {
        finish(new Error(message.message));
      }
    };
    worker.onerror = (event) => finish(new Error(event.message || 'GeoParquet worker failed'));
    worker.postMessage(buffer, [buffer]);
  });
}
