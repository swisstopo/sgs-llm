/// <reference lib="webworker" />

import { decodeGeoParquet, type DecodedFeature } from './geoparquet';

const CHUNK_SIZE = 2_000;

self.onmessage = (event: MessageEvent<ArrayBuffer>) => {
  void decode(event.data);
};

async function decode(buffer: ArrayBuffer): Promise<void> {
  try {
    const features = await decodeGeoParquet(buffer);
    for (let start = 0; start < features.length; start += CHUNK_SIZE) {
      const chunk: DecodedFeature[] = features.slice(start, start + CHUNK_SIZE);
      self.postMessage({ type: 'chunk', features: chunk });
    }
    self.postMessage({ type: 'done' });
  } catch (error) {
    self.postMessage({
      type: 'error',
      message: error instanceof Error ? error.message : 'Could not decode GeoParquet',
    });
  }
}

export {};
