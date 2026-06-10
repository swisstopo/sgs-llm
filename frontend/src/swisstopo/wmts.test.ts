import { describe, expect, it } from 'vitest';
import { isWmtsDisplayable, wmtsTileUrl } from './wmts';
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

describe('wmtsTileUrl', () => {
  it('builds the LV95 tile template from the layer config', () => {
    const layer = { ...config('wmts'), format: 'jpeg', timestamps: ['current'] };
    expect(wmtsTileUrl(layer)).toBe(
      'https://wmts.geo.admin.ch/1.0.0/ch.swisstopo.example/default/current/2056/{z}/{x}/{y}.jpeg',
    );
  });
});
