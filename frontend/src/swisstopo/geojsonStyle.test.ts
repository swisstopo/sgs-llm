import { describe, expect, it } from 'vitest';
import Feature from 'ol/Feature';
import LineString from 'ol/geom/LineString';
import Point from 'ol/geom/Point';
import Polygon from 'ol/geom/Polygon';
import CircleStyle from 'ol/style/Circle';
import Icon from 'ol/style/Icon';
import RegularShape from 'ol/style/RegularShape';
import Style from 'ol/style/Style';
import { defaultGeoJsonStyle, parseGeoAdminStyle, resolveStyleUrl } from './geojsonStyle';

function point(properties: Record<string, unknown>): Feature {
  const feature = new Feature(new Point([0, 0]));
  feature.setProperties(properties);
  return feature;
}

/** Trimmed from ch.bafu.hydroweb-messstationen_gefahren. */
const UNIQUE_SPEC = {
  type: 'unique',
  property: 'symbol_design',
  values: [
    {
      geomType: 'point',
      value: 0.1,
      minResolution: 100,
      vectorOptions: { type: 'icon', src: 'https://example.ch/nodata14.png' },
    },
    {
      geomType: 'point',
      value: 0.1,
      maxResolution: 100,
      vectorOptions: {
        type: 'icon',
        src: 'https://example.ch/nodata16.png',
        label: {
          template: '${name}',
          text: {
            textAlign: 'center',
            font: 'bold 12px sans-serif',
            offsetY: -28,
            fill: { color: 'white' },
            backgroundFill: { color: 'rgba(14,80,114,0.9)' },
          },
        },
      },
    },
  ],
};

/** Trimmed from ch.meteoschweiz.messwerte-globalstrahlung-1d. */
const RANGE_SPEC = {
  type: 'range',
  property: 'value',
  ranges: [
    {
      geomType: 'point',
      range: [0, 30],
      vectorOptions: {
        type: 'circle',
        radius: 6,
        fill: { color: 'rgba(255,255,204,0.9)' },
        stroke: { color: 'rgba(14,80,114,0.9)', width: 2 },
      },
    },
    {
      geomType: 'point',
      range: [30, 100],
      vectorOptions: { type: 'circle', radius: 9, fill: { color: 'rgba(255,237,160,0.9)' } },
    },
  ],
};

describe('parseGeoAdminStyle', () => {
  it('matches unique values loosely and honors resolution windows', () => {
    const style = parseGeoAdminStyle(UNIQUE_SPEC)!;
    const feature = point({ symbol_design: 0.1, name: 'Bern' });

    const zoomedOut = style(feature, 200) as Style;
    expect((zoomedOut.getImage() as Icon).getSrc()).toBe('https://example.ch/nodata14.png');
    expect(zoomedOut.getText()).toBeNull();

    // String-typed property values match numeric rule values.
    expect(style(point({ symbol_design: '0.1' }), 200)).toBe(zoomedOut);
  });

  it('resolves label templates from feature properties and caches per text', () => {
    const style = parseGeoAdminStyle(UNIQUE_SPEC)!;
    const bern = point({ symbol_design: 0.1, name: 'Bern' });

    const labeled = style(bern, 50) as Style;
    expect((labeled.getImage() as Icon).getSrc()).toBe('https://example.ch/nodata16.png');
    expect(labeled.getText()?.getText()).toBe('Bern');
    expect(labeled.getText()?.getFont()).toBe('bold 12px sans-serif');
    expect(style(point({ symbol_design: 0.1, name: 'Bern' }), 50)).toBe(labeled);
    expect(
      (style(point({ symbol_design: 0.1, name: 'Chur' }), 50) as Style).getText()?.getText(),
    ).toBe('Chur');
  });

  it('returns no style when no rule matches', () => {
    const style = parseGeoAdminStyle(UNIQUE_SPEC)!;
    expect(style(point({ symbol_design: 9 }), 200)).toBeUndefined();
    // Wrong geometry category for the point rules.
    const line = new Feature(
      new LineString([
        [0, 0],
        [1, 1],
      ]),
    );
    line.set('symbol_design', 0.1);
    expect(style(line, 200)).toBeUndefined();
  });

  it('matches ranges inclusively on numeric values', () => {
    const style = parseGeoAdminStyle(RANGE_SPEC)!;
    const low = style(point({ value: 15 }), 100) as Style;
    expect((low.getImage() as CircleStyle).getRadius()).toBe(6);
    // Overlapping bound: the first matching rule wins.
    expect((style(point({ value: 30 }), 100) as Style).getImage()).toBe(low.getImage());
    expect((style(point({ value: 45 }), 100) as Style as Style).getImage()).not.toBe(
      low.getImage(),
    );
    expect(style(point({ value: -5 }), 100)).toBeUndefined();
    expect(style(point({ value: 'n/a' }), 100)).toBeUndefined();
  });

  it('supports single specs and regular shape markers', () => {
    const style = parseGeoAdminStyle({
      type: 'single',
      geomType: 'point',
      vectorOptions: { type: 'triangle', radius: 8, fill: { color: '#ff0000' } },
    })!;
    const shape = (style(point({}), 100) as Style).getImage() as RegularShape;
    expect(shape).toBeInstanceOf(RegularShape);
    expect(shape.getPoints()).toBe(3);
  });

  it('styles line/polygon rules without a marker type', () => {
    const style = parseGeoAdminStyle({
      type: 'unique',
      property: 'kind',
      values: [
        {
          geomType: 'polygon',
          value: 'zone',
          vectorOptions: {
            fill: { color: 'rgba(0,0,255,0.3)' },
            stroke: { color: 'blue', width: 2 },
          },
        },
      ],
    })!;
    const polygon = new Feature(
      new Polygon([
        [
          [0, 0],
          [1, 0],
          [1, 1],
          [0, 0],
        ],
      ]),
    );
    polygon.set('kind', 'zone');
    const styled = style(polygon, 100) as Style;
    expect(styled.getFill()?.getColor()).toBe('rgba(0,0,255,0.3)');
    expect(styled.getStroke()?.getWidth()).toBe(2);
  });

  it('rejects unrecognizable documents', () => {
    expect(parseGeoAdminStyle(null)).toBeUndefined();
    expect(parseGeoAdminStyle('x')).toBeUndefined();
    expect(parseGeoAdminStyle({})).toBeUndefined();
    expect(parseGeoAdminStyle({ type: 'unique' })).toBeUndefined();
    expect(parseGeoAdminStyle({ type: 'unique', property: 'p', values: [{}] })).toBeUndefined();
  });
});

describe('resolveStyleUrl', () => {
  it('normalizes protocol-relative URLs to https', () => {
    expect(resolveStyleUrl('//api3.geo.admin.ch/static/vectorStyles/x.json')).toBe(
      'https://api3.geo.admin.ch/static/vectorStyles/x.json',
    );
    expect(resolveStyleUrl('https://api3.geo.admin.ch/x.json')).toBe(
      'https://api3.geo.admin.ch/x.json',
    );
  });
});

describe('defaultGeoJsonStyle', () => {
  it('covers points, lines, and polygons', () => {
    const style = defaultGeoJsonStyle();
    expect(style.getImage()).toBeInstanceOf(CircleStyle);
    expect(style.getFill()).not.toBeNull();
    expect(style.getStroke()).not.toBeNull();
  });
});
