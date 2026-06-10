import JSON5 from 'json5';
import layerOverridesRaw from '../../../layers/layers_wmts.json5?raw';

export interface LayerOverride {
  id: string;
  defaultOpacity?: number;
}

/** Parses and validates the per-layer overrides (layers/layers_wmts.json5). */
export function parseLayerOverrides(raw: string): Map<string, LayerOverride> {
  const parsed: unknown = JSON5.parse(raw);
  const result = new Map<string, LayerOverride>();
  if (
    typeof parsed !== 'object' ||
    parsed === null ||
    !Array.isArray((parsed as { layers?: unknown }).layers)
  ) {
    throw new Error('layers_wmts.json5: expected a top-level "layers" array');
  }
  for (const entry of (parsed as { layers: unknown[] }).layers) {
    if (typeof entry !== 'object' || entry === null) {
      continue;
    }
    const layer = entry as Record<string, unknown>;
    if (typeof layer.id !== 'string') {
      throw new Error('layers_wmts.json5: every layer override needs a string "id"');
    }
    result.set(layer.id, {
      id: layer.id,
      defaultOpacity: typeof layer.defaultOpacity === 'number' ? layer.defaultOpacity : undefined,
    });
  }
  return result;
}

export function loadLayerOverrides(): Map<string, LayerOverride> {
  return parseLayerOverrides(layerOverridesRaw);
}
