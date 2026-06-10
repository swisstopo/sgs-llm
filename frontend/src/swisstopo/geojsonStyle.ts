import CircleStyle from 'ol/style/Circle';
import Fill from 'ol/style/Fill';
import Icon from 'ol/style/Icon';
import RegularShape from 'ol/style/RegularShape';
import Stroke from 'ol/style/Stroke';
import Style from 'ol/style/Style';
import Text from 'ol/style/Text';
import type { StyleFunction } from 'ol/style/Style';
import type { Options as TextOptions } from 'ol/style/Text';
import type ImageStyle from 'ol/style/Image';
import type { FeatureLike } from 'ol/Feature';
import { hexToRgba } from '../map/dataLayerStyle';
import { fetchJson } from './http';

/**
 * Parser for geoadmin's vector style JSON (served from
 * api3.geo.admin.ch/static/vectorStyles/*.json), covering the subset used by
 * the live `geojson` layers: top-level types `single`/`unique`/`range`,
 * point markers (circle, icon, regular shapes), line/polygon fill+stroke,
 * resolution windows, and `${property}` label templates. Property-driven
 * icon rotation and geometry-modifying styles are not supported; such rules
 * render without the unsupported aspect, and unparseable documents fall back
 * to {@link defaultGeoJsonStyle}.
 */

type Raw = Record<string, unknown>;

interface ParsedRule {
  geomType?: string;
  minResolution?: number;
  maxResolution?: number;
  /** Per-spec-type predicate on the feature's styling property value. */
  matches: (value: unknown) => boolean;
  base: Style;
  /** Label parts, when the rule carries one. */
  template?: string;
  textOptions?: TextOptions;
  /** Label styles per resolved text (data sets are small, a few hundred features). */
  textCache: Map<string, Style>;
}

function asObject(value: unknown): Raw | undefined {
  return typeof value === 'object' && value !== null ? (value as Raw) : undefined;
}

function asNumber(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined;
}

function buildFill(raw: unknown): Fill | undefined {
  const options = asObject(raw);
  return options && typeof options.color === 'string'
    ? new Fill({ color: options.color })
    : undefined;
}

function buildStroke(raw: unknown): Stroke | undefined {
  const options = asObject(raw);
  if (!options || typeof options.color !== 'string') {
    return undefined;
  }
  return new Stroke({
    color: options.color,
    width: asNumber(options.width),
    lineDash: Array.isArray(options.lineDash)
      ? options.lineDash.filter((n): n is number => typeof n === 'number')
      : undefined,
  });
}

/** Marker geometries supported via ol RegularShape, as in geoadmin's viewer. */
const REGULAR_SHAPES: Record<
  string,
  { points: number; angle?: number; radius2?: (r: number) => number }
> = {
  square: { points: 4, angle: Math.PI / 4 },
  triangle: { points: 3 },
  pentagon: { points: 5 },
  hexagon: { points: 6 },
  star: { points: 5, radius2: (radius) => radius / 2 },
  cross: { points: 4, radius2: () => 0 },
};

function buildImage(options: Raw): ImageStyle | undefined {
  const type = options.type;
  if (type === 'circle') {
    return new CircleStyle({
      radius: asNumber(options.radius) ?? 5,
      fill: buildFill(options.fill),
      stroke: buildStroke(options.stroke),
    });
  }
  if (type === 'icon') {
    if (typeof options.src !== 'string') {
      return undefined;
    }
    return new Icon({
      src: options.src,
      scale: asNumber(options.scale),
      anchor: Array.isArray(options.anchor) ? (options.anchor as number[]) : undefined,
      rotation: asNumber(options.rotation),
      crossOrigin: 'anonymous',
    });
  }
  const shape = typeof type === 'string' ? REGULAR_SHAPES[type] : undefined;
  if (shape) {
    const radius = asNumber(options.radius) ?? 5;
    return new RegularShape({
      points: shape.points,
      radius,
      radius2: shape.radius2?.(radius),
      angle: shape.angle ?? 0,
      rotation: asNumber(options.rotation) ?? 0,
      fill: buildFill(options.fill),
      stroke: buildStroke(options.stroke),
    });
  }
  return undefined;
}

/** ol Text options from a label's `text` block (everything except the string itself). */
function buildTextOptions(raw: unknown): TextOptions | undefined {
  const options = asObject(raw);
  if (!options) {
    return undefined;
  }
  return {
    font: typeof options.font === 'string' ? options.font : undefined,
    scale: asNumber(options.scale),
    offsetX: asNumber(options.offsetX),
    offsetY: asNumber(options.offsetY),
    textAlign:
      typeof options.textAlign === 'string'
        ? (options.textAlign as TextOptions['textAlign'])
        : undefined,
    textBaseline:
      typeof options.textBaseline === 'string'
        ? (options.textBaseline as TextOptions['textBaseline'])
        : undefined,
    padding: Array.isArray(options.padding)
      ? options.padding.filter((n): n is number => typeof n === 'number')
      : undefined,
    fill: buildFill(options.fill),
    stroke: buildStroke(options.stroke),
    backgroundFill: buildFill(options.backgroundFill),
    backgroundStroke: buildStroke(options.backgroundStroke),
  };
}

/** Builds one rule; returns undefined when its vectorOptions are unusable. */
function parseRule(raw: Raw, matches: (value: unknown) => boolean): ParsedRule | undefined {
  const vectorOptions = asObject(raw.vectorOptions);
  if (!vectorOptions) {
    return undefined;
  }
  let base: Style;
  if (typeof vectorOptions.type === 'string') {
    const image = buildImage(vectorOptions);
    if (!image) {
      return undefined;
    }
    base = new Style({ image });
  } else {
    // Line/polygon rules carry plain fill/stroke without a marker type.
    base = new Style({
      fill: buildFill(vectorOptions.fill),
      stroke: buildStroke(vectorOptions.stroke),
    });
  }
  const label = asObject(vectorOptions.label);
  const template = label && typeof label.template === 'string' ? label.template : undefined;
  return {
    geomType: typeof raw.geomType === 'string' ? raw.geomType : undefined,
    minResolution: asNumber(raw.minResolution),
    maxResolution: asNumber(raw.maxResolution),
    matches,
    base,
    template,
    textOptions: template ? (buildTextOptions(label?.text) ?? {}) : undefined,
    textCache: new Map(),
  };
}

function geomCategory(feature: FeatureLike): string | undefined {
  switch (feature.getGeometry()?.getType()) {
    case 'Point':
    case 'MultiPoint':
      return 'point';
    case 'LineString':
    case 'MultiLineString':
      return 'line';
    case 'Polygon':
    case 'MultiPolygon':
      return 'polygon';
    default:
      return undefined;
  }
}

function resolveTemplate(template: string, feature: FeatureLike): string {
  return template.replace(/\$\{([^}]+)\}/g, (_, property: string) => {
    const value: unknown = feature.get(property.trim());
    return value === undefined || value === null ? '' : String(value);
  });
}

function ruleStyle(rule: ParsedRule, feature: FeatureLike): Style {
  if (!rule.template) {
    return rule.base;
  }
  const text = resolveTemplate(rule.template, feature);
  let style = rule.textCache.get(text);
  if (!style) {
    style = rule.base.clone();
    style.setText(new Text({ ...rule.textOptions, text }));
    rule.textCache.set(text, style);
  }
  return style;
}

/**
 * Parses a geoadmin vector style document into an OpenLayers style function.
 * Returns undefined when the document is not a recognizable geoadmin style —
 * callers fall back to {@link defaultGeoJsonStyle}.
 */
export function parseGeoAdminStyle(raw: unknown): StyleFunction | undefined {
  try {
    const spec = asObject(raw);
    if (!spec) {
      return undefined;
    }
    const property = typeof spec.property === 'string' ? spec.property : undefined;
    let rules: ParsedRule[];
    if (spec.type === 'single') {
      const rule = parseRule(spec, () => true);
      rules = rule ? [rule] : [];
    } else if (spec.type === 'unique' && property && Array.isArray(spec.values)) {
      rules = spec.values
        .map((entry) => {
          const rule = asObject(entry);
          // Geoadmin matches loosely; live data mixes numeric and string values.
          return rule
            ? parseRule(rule, (value) => String(value) === String(rule.value))
            : undefined;
        })
        .filter((rule): rule is ParsedRule => rule !== undefined);
    } else if (spec.type === 'range' && property && Array.isArray(spec.ranges)) {
      rules = spec.ranges
        .map((entry) => {
          const rule = asObject(entry);
          if (!rule || !Array.isArray(rule.range)) {
            return undefined;
          }
          const [min, max] = rule.range as [unknown, unknown];
          if (typeof min !== 'number' || typeof max !== 'number') {
            return undefined;
          }
          return parseRule(rule, (value) => {
            const numeric = Number(value);
            return Number.isFinite(numeric) && numeric >= min && numeric <= max;
          });
        })
        .filter((rule): rule is ParsedRule => rule !== undefined);
    } else {
      return undefined;
    }
    if (rules.length === 0) {
      return undefined;
    }
    return (feature, resolution) => {
      const geom = geomCategory(feature);
      const value: unknown = property ? feature.get(property) : undefined;
      for (const rule of rules) {
        if (rule.geomType !== undefined && rule.geomType !== geom) {
          continue;
        }
        if (rule.minResolution !== undefined && resolution < rule.minResolution) {
          continue;
        }
        if (rule.maxResolution !== undefined && resolution >= rule.maxResolution) {
          continue;
        }
        if (!rule.matches(value)) {
          continue;
        }
        return ruleStyle(rule, feature);
      }
      // No matching rule: the feature is not rendered (geoadmin behavior).
      return undefined;
    };
  } catch {
    return undefined;
  }
}

const DEFAULT_COLOR = '#d8232a';

/** Fallback style for official geojson layers (mirrors the data-layer defaults). */
export function defaultGeoJsonStyle(): Style {
  const stroke = new Stroke({ color: DEFAULT_COLOR, width: 1.5 });
  return new Style({
    image: new CircleStyle({
      radius: 6,
      fill: new Fill({ color: hexToRgba(DEFAULT_COLOR, 0.85) }),
      stroke,
    }),
    fill: new Fill({ color: hexToRgba(DEFAULT_COLOR, 0.35) }),
    stroke,
  });
}

/** Normalizes a possibly protocol-relative style URL (`//api3...`) to https. */
export function resolveStyleUrl(url: string): string {
  return url.startsWith('//') ? `https:${url}` : url;
}

/** Fetches and parses a layer's style; never throws — falls back to the default style. */
export async function loadGeoAdminStyle(
  styleUrl: string | undefined,
): Promise<StyleFunction | Style> {
  if (!styleUrl) {
    return defaultGeoJsonStyle();
  }
  try {
    const parsed = parseGeoAdminStyle(await fetchJson(resolveStyleUrl(styleUrl)));
    if (!parsed) {
      console.warn(`Unrecognized layer style, using default: ${styleUrl}`);
    }
    return parsed ?? defaultGeoJsonStyle();
  } catch (error) {
    console.warn(`Failed to load layer style ${styleUrl}`, error);
    return defaultGeoJsonStyle();
  }
}
