import { describe, expect, it } from 'vitest';
import { isWmsDisplayable, wmsParams, wmsUrl } from './wms';
import type { LayerConfig } from './layersConfigApi';

function config(overrides: Partial<LayerConfig>): LayerConfig {
  return {
    id: 'ch.bav.sachplan-infrastruktur-schifffahrt_anhoerung',
    type: 'wms',
    label: 'SIF consultation',
    attribution: 'FOT',
    background: false,
    tooltip: false,
    hasLegend: true,
    wmsLayers: 'ch.bav.sachplan-infrastruktur-schifffahrt_anhoerung',
    ...overrides,
  };
}

describe('isWmsDisplayable', () => {
  it('requires the wms type and a LAYERS param', () => {
    expect(isWmsDisplayable(config({}))).toBe(true);
    expect(isWmsDisplayable(config({ type: 'wmts' }))).toBe(false);
    expect(isWmsDisplayable(config({ wmsLayers: undefined }))).toBe(false);
  });
});

describe('wmsUrl', () => {
  it('uses the layer endpoint when present', () => {
    expect(wmsUrl(config({ wmsUrl: 'https://wms.example.ch' }))).toBe('https://wms.example.ch');
  });

  it('falls back to the default service', () => {
    expect(wmsUrl(config({}))).toBe('https://wms.geo.admin.ch');
  });
});

describe('wmsParams', () => {
  it('builds LAYERS and FORMAT from the config', () => {
    expect(wmsParams(config({ format: 'jpeg' }))).toEqual({
      LAYERS: 'ch.bav.sachplan-infrastruktur-schifffahrt_anhoerung',
      FORMAT: 'image/jpeg',
    });
  });

  it('defaults to png', () => {
    expect(wmsParams(config({})).FORMAT).toBe('image/png');
  });

  it('passes comma-separated layer lists through verbatim', () => {
    expect(wmsParams(config({ wmsLayers: 'a,b,c' })).LAYERS).toBe('a,b,c');
  });
});
