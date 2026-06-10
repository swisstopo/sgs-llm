import { describe, expect, it } from 'vitest';
import { isDisplayable, isGeoJsonDisplayable, layerAttribution } from './layers';
import type { LayerConfig } from './layersConfigApi';

function config(overrides: Partial<LayerConfig>): LayerConfig {
  return {
    id: 'ch.swisstopo.example',
    type: 'wmts',
    label: 'Example',
    attribution: 'swisstopo',
    background: false,
    tooltip: false,
    hasLegend: false,
    ...overrides,
  };
}

describe('isDisplayable', () => {
  it('accepts wmts layers', () => {
    expect(isDisplayable(config({ type: 'wmts' }))).toBe(true);
  });

  it('accepts wms layers with a LAYERS param', () => {
    expect(isDisplayable(config({ type: 'wms', wmsLayers: 'ch.bav.sif' }))).toBe(true);
  });

  it('rejects wms layers without a LAYERS param', () => {
    expect(isDisplayable(config({ type: 'wms' }))).toBe(false);
    expect(isDisplayable(config({ type: 'wms', wmsLayers: '' }))).toBe(false);
  });

  it('accepts geojson layers with a data URL', () => {
    expect(
      isDisplayable(config({ type: 'geojson', geojsonUrl: 'https://data.geo.admin.ch/x.json' })),
    ).toBe(true);
  });

  it('rejects geojson layers without a data URL', () => {
    expect(isDisplayable(config({ type: 'geojson' }))).toBe(false);
    expect(isGeoJsonDisplayable(config({ type: 'geojson' }))).toBe(false);
  });

  it('rejects other layer types', () => {
    for (const type of ['aggregate', 'wmtsMercator', '']) {
      expect(isDisplayable(config({ type }))).toBe(false);
    }
  });
});

describe('layerAttribution', () => {
  it('links the attribution when a URL is present', () => {
    const attribution = layerAttribution(
      config({ attribution: 'BAFU', attributionUrl: 'https://www.bafu.admin.ch' }),
    );
    expect(attribution).toContain('<a href="https://www.bafu.admin.ch"');
    expect(attribution).toContain('© BAFU');
  });

  it('falls back to plain text without a URL', () => {
    expect(layerAttribution(config({ attribution: 'BAFU' }))).toBe('© BAFU');
  });
});
