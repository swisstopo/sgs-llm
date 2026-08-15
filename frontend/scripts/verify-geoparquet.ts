/// <reference types="node" />

import { readFile } from 'node:fs/promises';
import { resolve } from 'node:path';
import { decodeGeoParquet } from '../src/map/geoparquet';

const [pathArgument, expectedArgument] = process.argv.slice(2);
if (!pathArgument || !expectedArgument) {
  throw new Error('usage: verify-geoparquet.ts <path> <expected-feature-count>');
}
const expected = Number(expectedArgument);
if (!Number.isSafeInteger(expected) || expected < 0) {
  throw new Error(`invalid expected feature count: ${expectedArgument}`);
}

const bytes = await readFile(resolve(pathArgument));
const buffer = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
const started = performance.now();
const features = await decodeGeoParquet(buffer);
const elapsedMs = Math.round(performance.now() - started);

if (features.length !== expected) {
  throw new Error(`expected ${expected} features, decoded ${features.length}`);
}
if (features.some((feature) => !feature.geometry.type)) {
  throw new Error('at least one decoded feature has no geometry type');
}

console.log(
  JSON.stringify({
    bytes: bytes.byteLength,
    features: features.length,
    firstId: features[0]?.id,
    lastId: features.at(-1)?.id,
    elapsedMs,
  }),
);
