import { describe, expect, it } from 'vitest';
import { parseLayersConfig } from './layersConfigApi';

const SAMPLE = {
  'ch.swisstopo.pixelkarte-grau': {
    type: 'wmts',
    label: 'Landeskarten (grau)',
    attribution: 'swisstopo',
    attributionUrl: 'https://www.swisstopo.admin.ch/de/home.html',
    background: true,
    format: 'jpeg',
    timestamps: ['current'],
    tooltip: false,
    hasLegend: false,
  },
  'ch.bafu.wrz-wildruhezonen_portal': {
    type: 'wmts',
    label: 'Wildruhezonen',
    attribution: 'Kt. [BAFU]',
    background: false,
    format: 'png',
    timestamps: ['current'],
    opacity: 1.0,
    tooltip: true,
    hasLegend: true,
  },
  broken: { label: 42 },
};

describe('parseLayersConfig', () => {
  it('parses valid layer entries', () => {
    const config = parseLayersConfig(SAMPLE);
    const basemap = config.get('ch.swisstopo.pixelkarte-grau');
    expect(basemap).toMatchObject({
      id: 'ch.swisstopo.pixelkarte-grau',
      type: 'wmts',
      background: true,
      format: 'jpeg',
      timestamps: ['current'],
    });
    const overlay = config.get('ch.bafu.wrz-wildruhezonen_portal');
    expect(overlay).toMatchObject({ tooltip: true, hasLegend: true, background: false });
  });

  it('skips entries without type/label', () => {
    expect(parseLayersConfig(SAMPLE).has('broken')).toBe(false);
  });

  it('returns an empty map for malformed input', () => {
    expect(parseLayersConfig(null).size).toBe(0);
    expect(parseLayersConfig('x').size).toBe(0);
  });
});
