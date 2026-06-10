import { describe, expect, it } from 'vitest';
import { loadLayerOverrides, parseLayerOverrides } from './layerOverrides';

describe('parseLayerOverrides', () => {
  it('parses overrides keyed by id', () => {
    const overrides = parseLayerOverrides(`{ layers: [{ id: 'a', defaultOpacity: 0.5 }] }`);
    expect(overrides.get('a')?.defaultOpacity).toBe(0.5);
  });

  it('rejects missing layers array and missing ids', () => {
    expect(() => parseLayerOverrides('{}')).toThrow(/layers/);
    expect(() => parseLayerOverrides(`{ layers: [{ defaultOpacity: 1 }] }`)).toThrow(/id/);
  });
});

describe('bundled overrides file', () => {
  it('parses without errors', () => {
    expect(loadLayerOverrides().size).toBeGreaterThan(0);
  });
});
