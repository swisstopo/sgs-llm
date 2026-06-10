import { describe, expect, it } from 'vitest';
import { isWmtsDisplayable } from './wmts';
import type { LayerConfig } from './layersConfigApi';

function config(type: string): LayerConfig {
  return {
    id: 'ch.swisstopo.example',
    type,
    label: 'Example',
    attribution: 'swisstopo',
    background: false,
    tooltip: false,
    hasLegend: false,
  };
}

describe('isWmtsDisplayable', () => {
  it('is true only for wmts layers', () => {
    expect(isWmtsDisplayable(config('wmts'))).toBe(true);
  });

  it('is false for non-wmts layer types', () => {
    for (const type of ['wms', 'aggregate', 'geojson', 'wmtsMercator', '']) {
      expect(isWmtsDisplayable(config(type))).toBe(false);
    }
  });
});
