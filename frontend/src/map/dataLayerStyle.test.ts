import { describe, expect, it } from 'vitest';
import CircleStyle from 'ol/style/Circle';
import { buildDataLayerStyle, hexToRgba } from './dataLayerStyle';
import type { LayerSpec } from '../protocol/v1';

const baseSpec: LayerSpec = {
  id: 'l1',
  name: 'Test',
  format: 'geojson',
  url: 'http://localhost/x.geojson',
  geometry_type: 'polygon',
};

describe('hexToRgba', () => {
  it('converts 6-digit and 3-digit hex', () => {
    expect(hexToRgba('#1c64f2', 0.4)).toBe('rgba(28, 100, 242, 0.4)');
    expect(hexToRgba('#f00', 1)).toBe('rgba(255, 0, 0, 1)');
  });

  it('passes through non-hex expressions', () => {
    expect(hexToRgba('rebeccapurple', 0.5)).toBe('rebeccapurple');
  });
});

describe('buildDataLayerStyle', () => {
  it('applies fill + stroke hints for polygons', () => {
    const style = buildDataLayerStyle({
      ...baseSpec,
      style_hint: { fill_color: '#1c64f2', stroke_color: '#1e429f', opacity: 0.45 },
    });
    expect(style.getFill()?.getColor()).toBe('rgba(28, 100, 242, 0.45)');
    expect(style.getStroke()?.getColor()).toBe('#1e429f');
  });

  it('renders points as circles with hinted radius', () => {
    const style = buildDataLayerStyle({
      ...baseSpec,
      geometry_type: 'point',
      style_hint: { point_radius: 8 },
    });
    const image = style.getImage();
    expect(image).toBeInstanceOf(CircleStyle);
    expect((image as CircleStyle).getRadius()).toBe(8);
  });

  it('uses defaults without hints', () => {
    const style = buildDataLayerStyle(baseSpec);
    expect(style.getFill()?.getColor()).toBe('rgba(216, 35, 42, 0.35)');
    expect(style.getStroke()?.getWidth()).toBe(1.5);
  });
});
