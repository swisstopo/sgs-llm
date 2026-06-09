import { describe, expect, it } from 'vitest';
import {
  loadLayerOverrides,
  loadLayerTree,
  parseLayerOverrides,
  parseLayerTree,
} from './loadLayerTree';

describe('parseLayerTree', () => {
  it('parses a valid tree', () => {
    const groups = parseLayerTree(`{
      groups: [
        {
          id: 'env',
          label: { de: 'Umwelt', fr: 'Environnement', it: 'Ambiente', en: 'Environment' },
          children: ['ch.bafu.waldreservate'],
        },
      ],
    }`);
    expect(groups).toHaveLength(1);
    expect(groups[0]?.children).toEqual(['ch.bafu.waldreservate']);
  });

  it('rejects groups with missing language labels', () => {
    expect(() =>
      parseLayerTree(`{ groups: [{ id: 'x', label: { de: 'a' }, children: [] }] }`),
    ).toThrow(/labels for de\/fr\/it\/en/);
  });

  it('rejects a missing groups array', () => {
    expect(() => parseLayerTree('{}')).toThrow(/groups/);
  });
});

describe('parseLayerOverrides', () => {
  it('parses overrides keyed by id', () => {
    const overrides = parseLayerOverrides(`{ layers: [{ id: 'a', defaultOpacity: 0.5 }] }`);
    expect(overrides.get('a')?.defaultOpacity).toBe(0.5);
  });
});

describe('bundled catalog files', () => {
  it('parse without errors and reference each group', () => {
    const groups = loadLayerTree();
    expect(groups.length).toBeGreaterThan(0);
    for (const group of groups) {
      expect(group.children.length).toBeGreaterThan(0);
    }
    // Overrides must reference layers present in the tree.
    const allChildren = new Set(groups.flatMap((g) => g.children));
    for (const id of loadLayerOverrides().keys()) {
      expect(allChildren.has(id)).toBe(true);
    }
  });
});
