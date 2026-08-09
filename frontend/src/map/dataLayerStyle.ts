import Fill from 'ol/style/Fill';
import Stroke from 'ol/style/Stroke';
import CircleStyle from 'ol/style/Circle';
import Style from 'ol/style/Style';
import type { LayerSpec, StyleHint } from '../protocol/v1';

export const DEFAULT_COLOR = '#d8232a';
const DEFAULT_FILL_OPACITY = 0.35;
const DEFAULT_POINT_OPACITY = 0.85;

/** A `style_hint` with every default filled in - what the symbology editor shows. */
export interface ResolvedStyle {
  fillColor: string;
  strokeColor: string;
  strokeWidth: number;
  pointRadius: number;
  opacity: number;
}

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

/** Fills in the per-geometry defaults a `style_hint` leaves out. */
export function resolveStyle(spec: LayerSpec): ResolvedStyle {
  const hint: StyleHint = spec.style_hint ?? {};
  const fillColor = hint.fill_color ?? DEFAULT_COLOR;
  const isPoint = spec.geometry_type === 'point';
  return {
    fillColor,
    strokeColor: hint.stroke_color ?? fillColor,
    strokeWidth: hint.stroke_width ?? (spec.geometry_type === 'line' ? 2.5 : 1.5),
    pointRadius: hint.point_radius ?? 6,
    opacity: hint.opacity ?? (isPoint ? DEFAULT_POINT_OPACITY : DEFAULT_FILL_OPACITY),
  };
}

/**
 * Maps a protocol `style_hint` onto an OpenLayers style, with sensible
 * defaults per geometry type.
 */
export function buildDataLayerStyle(spec: LayerSpec): Style {
  const resolved = resolveStyle(spec);
  const fill = new Fill({ color: hexToRgba(resolved.fillColor, resolved.opacity) });
  const stroke = new Stroke({ color: resolved.strokeColor, width: resolved.strokeWidth });

  if (spec.geometry_type === 'point') {
    return new Style({
      image: new CircleStyle({ radius: resolved.pointRadius, fill, stroke }),
    });
  }
  return new Style({ fill, stroke });
}
