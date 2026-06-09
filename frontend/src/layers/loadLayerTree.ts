import JSON5 from 'json5';
import layerTreeRaw from '../../../layers/layertree.json5?raw';
import layerOverridesRaw from '../../../layers/layers_wmts.json5?raw';
import type { AppLanguage } from '../i18n/i18n';

export interface LayerTreeGroup {
  id: string;
  label: Record<AppLanguage, string>;
  children: string[];
}

export interface LayerOverride {
  id: string;
  defaultOpacity?: number;
}

function isLabelRecord(value: unknown): value is Record<AppLanguage, string> {
  if (typeof value !== 'object' || value === null) {
    return false;
  }
  const record = value as Record<string, unknown>;
  return (['de', 'fr', 'it', 'en'] as const).every((lang) => typeof record[lang] === 'string');
}

/** Parses and validates the curated layer tree (layers/layertree.json5). */
export function parseLayerTree(raw: string): LayerTreeGroup[] {
  const parsed: unknown = JSON5.parse(raw);
  if (
    typeof parsed !== 'object' ||
    parsed === null ||
    !Array.isArray((parsed as { groups?: unknown }).groups)
  ) {
    throw new Error('layertree.json5: expected a top-level "groups" array');
  }
  const groups: LayerTreeGroup[] = [];
  for (const entry of (parsed as { groups: unknown[] }).groups) {
    if (typeof entry !== 'object' || entry === null) {
      throw new Error('layertree.json5: group entries must be objects');
    }
    const group = entry as Record<string, unknown>;
    if (typeof group.id !== 'string' || group.id.length === 0) {
      throw new Error('layertree.json5: every group needs a string "id"');
    }
    if (!isLabelRecord(group.label)) {
      throw new Error(`layertree.json5: group "${group.id}" needs labels for de/fr/it/en`);
    }
    if (
      !Array.isArray(group.children) ||
      !group.children.every((child): child is string => typeof child === 'string')
    ) {
      throw new Error(`layertree.json5: group "${group.id}" needs a string array "children"`);
    }
    groups.push({ id: group.id, label: group.label, children: group.children });
  }
  return groups;
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

export function loadLayerTree(): LayerTreeGroup[] {
  return parseLayerTree(layerTreeRaw);
}

export function loadLayerOverrides(): Map<string, LayerOverride> {
  return parseLayerOverrides(layerOverridesRaw);
}
