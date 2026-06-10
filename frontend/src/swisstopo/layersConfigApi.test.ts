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
  'ch.bav.sachplan-infrastruktur-schifffahrt_anhoerung': {
    type: 'wms',
    label: 'SIF consultation',
    attribution: 'FOT',
    background: false,
    wmsUrl: 'https://wms.geo.admin.ch',
    wmsLayers: 'ch.bav.sachplan-infrastruktur-schifffahrt_anhoerung',
    singleTile: true,
    format: 'png',
    opacity: 0.75,
    tooltip: false,
    hasLegend: true,
  },
  'ch.swisstopo.meldungen-karten_geodaten': {
    type: 'geojson',
    label: 'Notifications for maps and geodata',
    attribution: 'swisstopo',
    background: false,
    geojsonUrl: 'https://data.geo.admin.ch/ch.swisstopo.meldungen-karten_geodaten/x_en.json',
    styleUrl: '//api3.geo.admin.ch/static/vectorStyles/ch.swisstopo.meldungen-karten_geodaten.json',
    updateDelay: 450000,
    tooltip: false,
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
    expect(overlay?.wmsLayers).toBeUndefined();
    expect(overlay?.geojsonUrl).toBeUndefined();
    expect(overlay?.singleTile).toBe(false);
  });

  it('parses WMS service fields', () => {
    const wms = parseLayersConfig(SAMPLE).get(
      'ch.bav.sachplan-infrastruktur-schifffahrt_anhoerung',
    );
    expect(wms).toMatchObject({
      type: 'wms',
      wmsUrl: 'https://wms.geo.admin.ch',
      wmsLayers: 'ch.bav.sachplan-infrastruktur-schifffahrt_anhoerung',
      singleTile: true,
      format: 'png',
      opacity: 0.75,
    });
    expect(wms?.gutter).toBeUndefined();
  });

  it('parses GeoJSON service fields', () => {
    const geojson = parseLayersConfig(SAMPLE).get('ch.swisstopo.meldungen-karten_geodaten');
    expect(geojson).toMatchObject({
      type: 'geojson',
      geojsonUrl: 'https://data.geo.admin.ch/ch.swisstopo.meldungen-karten_geodaten/x_en.json',
      styleUrl:
        '//api3.geo.admin.ch/static/vectorStyles/ch.swisstopo.meldungen-karten_geodaten.json',
      updateDelay: 450000,
    });
  });

  it('skips entries without type/label', () => {
    expect(parseLayersConfig(SAMPLE).has('broken')).toBe(false);
  });

  it('returns an empty map for malformed input', () => {
    expect(parseLayersConfig(null).size).toBe(0);
    expect(parseLayersConfig('x').size).toBe(0);
  });
});
