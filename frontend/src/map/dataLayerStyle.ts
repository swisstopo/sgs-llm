import Fill from 'ol/style/Fill';
import Stroke from 'ol/style/Stroke';
import CircleStyle from 'ol/style/Circle';
import Style from 'ol/style/Style';
import type { LayerSpec, StyleHint } from '../protocol/v1';

const DEFAULT_COLOR = '#d8232a';
const DEFAULT_FILL_OPACITY = 0.35;

/** Converts a #rgb/#rrggbb hex color to rgba() with the given alpha. */
export function hexToRgba(hex: string, alpha: number): string {
  const match = /^#([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(hex.trim());
  if (!match) {
    return hex; // pass through non-hex color expressions unchanged
  }
  let value = match[1]!;
  if (value.length === 3) {
    value = [...value].map((c) => c + c).join('');
  }
  const r = parseInt(value.slice(0, 2), 16);
  const g = parseInt(value.slice(2, 4), 16);
  const b = parseInt(value.slice(4, 6), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/**
 * Maps a protocol `style_hint` onto an OpenLayers style, with sensible
 * defaults per geometry type.
 */
export function buildDataLayerStyle(spec: LayerSpec): Style {
  const hint: StyleHint = spec.style_hint ?? {};
  const baseColor = hint.fill_color ?? DEFAULT_COLOR;
  const strokeColor = hint.stroke_color ?? hint.fill_color ?? DEFAULT_COLOR;
  const fillOpacity = hint.opacity ?? DEFAULT_FILL_OPACITY;
  const fill = new Fill({ color: hexToRgba(baseColor, fillOpacity) });
  const stroke = new Stroke({
    color: strokeColor,
    width: hint.stroke_width ?? (spec.geometry_type === 'line' ? 2.5 : 1.5),
  });

  if (spec.geometry_type === 'point') {
    return new Style({
      image: new CircleStyle({
        radius: hint.point_radius ?? 6,
        fill: new Fill({ color: hexToRgba(baseColor, hint.opacity ?? 0.85) }),
        stroke,
      }),
    });
  }
  return new Style({ fill, stroke });
}
