import MVT from 'ol/format/MVT';
import VectorTileLayer from 'ol/layer/VectorTile';
import type Tile from 'ol/Tile';
import TileState from 'ol/TileState';
import type VectorTile from 'ol/VectorTile';
import type RenderFeature from 'ol/render/Feature';
import type Projection from 'ol/proj/Projection';
import VectorTileSource from 'ol/source/VectorTile';
import { createXYZ } from 'ol/tilegrid';
import type { LayerSpec } from '../protocol/v1';
import { buildDataLayerStyle } from './dataLayerStyle';

const MAX_ACTIVE_REQUESTS = 6;
const REQUEST_DEBOUNCE_MS = 200;
const MAX_FETCH_ATTEMPTS = 3;

export interface MvtLayerCallbacks {
  onExpired?: () => void;
}

function abortError(): DOMException {
  return new DOMException('The tile request was aborted', 'AbortError');
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

class GeneratedLayerExpired extends Error {}

function delay(milliseconds: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal.aborted) {
      reject(abortError());
      return;
    }
    const timer = window.setTimeout(() => {
      signal.removeEventListener('abort', aborted);
      resolve();
    }, milliseconds);
    const aborted = () => {
      window.clearTimeout(timer);
      reject(abortError());
    };
    signal.addEventListener('abort', aborted, { once: true });
  });
}

class TileRequestQueue {
  private active = 0;
  private readonly waiters: Array<() => void> = [];

  async schedule<T>(signal: AbortSignal, operation: () => Promise<T>): Promise<T> {
    await delay(REQUEST_DEBOUNCE_MS, signal);
    await this.acquire(signal);
    try {
      return await operation();
    } finally {
      this.release();
    }
  }

  private acquire(signal: AbortSignal): Promise<void> {
    if (signal.aborted) {
      return Promise.reject(abortError());
    }
    if (this.active < MAX_ACTIVE_REQUESTS) {
      this.active += 1;
      return Promise.resolve();
    }
    return new Promise((resolve, reject) => {
      const ready = () => {
        signal.removeEventListener('abort', aborted);
        this.active += 1;
        resolve();
      };
      const aborted = () => {
        const index = this.waiters.indexOf(ready);
        if (index >= 0) {
          this.waiters.splice(index, 1);
        }
        reject(abortError());
      };
      this.waiters.push(ready);
      signal.addEventListener('abort', aborted, { once: true });
    });
  }

  private release(): void {
    this.active -= 1;
    this.waiters.shift()?.();
  }
}

// One browser-wide bound: opening several generated layers must not multiply
// backend pressure by six per source.
const tileRequestQueue = new TileRequestQueue();

export function expandTileTemplate(template: string, z: number, x: number, y: number): string {
  return template
    .replaceAll('{z}', String(z))
    .replaceAll('{x}', String(x))
    .replaceAll('{y}', String(y));
}

export function isLayerExpired(spec: LayerSpec, now = Date.now()): boolean {
  if (!spec.url_expires_at) {
    return false;
  }
  const expiresAt = Date.parse(spec.url_expires_at);
  return Number.isFinite(expiresAt) && expiresAt <= now;
}

/** PublicForge-style visible MVT loading adapted to OpenLayers. */
export class MvtTileSource extends VectorTileSource<RenderFeature> {
  private readonly decoder: MVT<RenderFeature>;
  private readonly pending = new Set<AbortController>();

  constructor(
    private readonly spec: LayerSpec,
    private readonly callbacks: MvtLayerCallbacks = {},
  ) {
    // DuckDB ST_AsMVT writes __feature_id into the protobuf feature-id slot, not
    // into the public properties map. OpenLayers therefore reads the native id.
    const format = new MVT();
    super({
      format,
      projection: 'EPSG:3857',
      tileGrid: createXYZ({ minZoom: spec.min_zoom, maxZoom: spec.max_zoom, tileSize: 256 }),
      tileUrlFunction: ([z, x, y]) => `sgs-mvt://${z}/${x}/${y}`,
      attributions: spec.attribution ? [spec.attribution] : undefined,
      wrapX: false,
    });
    this.decoder = format;
    this.setTileLoadFunction(this.loadTile);
  }

  abortPending(): void {
    for (const controller of this.pending) {
      controller.abort();
    }
    this.pending.clear();
  }

  private readonly loadTile = (tile: Tile, sourceUrl: string): void => {
    const match = /^sgs-mvt:\/\/(\d+)\/(\d+)\/(\d+)$/.exec(sourceUrl);
    if (!match) {
      tile.setState(TileState.ERROR);
      return;
    }
    const vectorTile = tile as VectorTile<RenderFeature>;
    const [z, x, y] = match.slice(1).map(Number) as [number, number, number];
    vectorTile.setLoader((extent, _resolution, projection) => {
      const controller = new AbortController();
      this.pending.add(controller);
      void tileRequestQueue
        .schedule(controller.signal, () =>
          this.fetchFeatures(z, x, y, extent, projection, controller.signal),
        )
        .then((features) => {
          vectorTile.setFeatures(features);
          if (features.length === 0) {
            vectorTile.setState(TileState.EMPTY);
          }
        })
        .catch((error: unknown) => {
          vectorTile.setFeatures([]);
          vectorTile.setState(isAbort(error) ? TileState.EMPTY : TileState.ERROR);
        })
        .finally(() => this.pending.delete(controller));
    });
  };

  private async fetchFeatures(
    z: number,
    x: number,
    y: number,
    extent: number[],
    projection: Projection,
    signal: AbortSignal,
  ): Promise<RenderFeature[]> {
    if (isLayerExpired(this.spec)) {
      this.callbacks.onExpired?.();
      throw new GeneratedLayerExpired('generated layer expired');
    }
    const response = await this.fetchWithRetry(expandTileTemplate(this.spec.url, z, x, y), signal);
    if (response.status === 410) {
      this.callbacks.onExpired?.();
      throw new GeneratedLayerExpired('generated layer expired');
    }
    if (response.status === 204) {
      return [];
    }
    if (!response.ok) {
      throw new Error(`tile request failed: ${response.status}`);
    }
    const body = await response.arrayBuffer();
    if (body.byteLength === 0) {
      return [];
    }
    return this.decoder.readFeatures(body, {
      extent,
      featureProjection: projection,
    }) as RenderFeature[];
  }

  private async fetchWithRetry(url: string, signal: AbortSignal): Promise<Response> {
    for (let attempt = 0; attempt < MAX_FETCH_ATTEMPTS; attempt += 1) {
      try {
        const response = await fetch(url, { signal });
        if (![429, 503].includes(response.status) || attempt + 1 === MAX_FETCH_ATTEMPTS) {
          return response;
        }
        const retryAfter = Number(response.headers.get('retry-after'));
        const waitMs = Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter * 1000 : 250;
        await delay(waitMs, signal);
      } catch (error) {
        if (isAbort(error) || attempt + 1 === MAX_FETCH_ATTEMPTS) {
          throw error;
        }
        await delay(250, signal);
      }
    }
    throw new Error('tile retries exhausted');
  }
}

export function createMvtLayer(
  spec: LayerSpec,
  callbacks: MvtLayerCallbacks = {},
): VectorTileLayer<MvtTileSource> {
  const source = new MvtTileSource(spec, callbacks);
  return new VectorTileLayer({
    source,
    style: buildDataLayerStyle(spec),
    declutter: true,
    useInterimTilesOnError: true,
  });
}
