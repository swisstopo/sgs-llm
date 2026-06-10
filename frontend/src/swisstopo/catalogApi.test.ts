import { describe, expect, it } from 'vitest';
import { filterCatalogTree, parseCatalogTree, parseTopics } from './catalogApi';
import type { CatalogFolderNode } from './catalogApi';

describe('parseTopics', () => {
  it('extracts topic ids', () => {
    expect(parseTopics({ topics: [{ id: 'ech' }, { id: 'bafu' }, { broken: true }] })).toEqual([
      { id: 'ech' },
      { id: 'bafu' },
    ]);
  });

  it('returns empty for malformed input', () => {
    expect(parseTopics(null)).toEqual([]);
    expect(parseTopics({ topics: 'x' })).toEqual([]);
  });
});

const RAW_TREE = {
  results: {
    root: {
      id: 1,
      category: 'root',
      children: [
        {
          id: 2,
          category: 'topic',
          label: 'Nature and Environment',
          children: [
            {
              id: 3,
              label: 'Geology',
              children: [
                {
                  id: 4,
                  label: 'Aeromagnetics 500',
                  layerBodId: 'ch.x.aeromagnetik',
                  staging: 'prod',
                },
                { id: 5, label: 'Test layer', layerBodId: 'ch.x.test', staging: 'test' },
              ],
            },
          ],
        },
        { id: 6, label: 'Empty folder', children: [] },
        { broken: true },
      ],
    },
  },
};

describe('parseCatalogTree', () => {
  it('parses folders and leaves, skipping non-prod staging', () => {
    const root = parseCatalogTree(RAW_TREE);
    expect(root.children).toHaveLength(2);
    const nature = root.children[0];
    expect(nature).toMatchObject({ kind: 'folder', label: 'Nature and Environment' });
    if (nature?.kind === 'folder') {
      const geology = nature.children[0];
      expect(geology).toMatchObject({ kind: 'folder', label: 'Geology' });
      if (geology?.kind === 'folder') {
        expect(geology.children).toEqual([
          { kind: 'layer', id: 4, label: 'Aeromagnetics 500', layerBodId: 'ch.x.aeromagnetik' },
        ]);
      }
    }
  });

  it('returns an empty root for malformed input', () => {
    expect(parseCatalogTree(null).children).toEqual([]);
    expect(parseCatalogTree({ results: {} }).children).toEqual([]);
  });
});

describe('filterCatalogTree', () => {
  const tree: CatalogFolderNode = parseCatalogTree(RAW_TREE);

  it('returns the input for an empty query', () => {
    expect(filterCatalogTree(tree, '  ')).toBe(tree);
  });

  it('prunes to matching leaves (case-insensitive)', () => {
    const filtered = filterCatalogTree(tree, 'AEROMAG');
    expect(filtered).not.toBeNull();
    expect(filtered?.children).toHaveLength(1);
    const nature = filtered?.children[0];
    if (nature?.kind === 'folder') {
      const geology = nature.children[0];
      if (geology?.kind === 'folder') {
        expect(geology.children).toHaveLength(1);
      }
    }
  });

  it('keeps the whole subtree when a folder label matches', () => {
    const filtered = filterCatalogTree(tree, 'geology');
    const nature = filtered?.children[0];
    if (nature?.kind === 'folder') {
      const geology = nature.children[0];
      expect(geology).toMatchObject({ kind: 'folder', label: 'Geology' });
      if (geology?.kind === 'folder') {
        expect(geology.children).toHaveLength(1); // full subtree kept
      }
    }
  });

  it('returns null when nothing matches', () => {
    expect(filterCatalogTree(tree, 'zzz-no-match')).toBeNull();
  });
});
