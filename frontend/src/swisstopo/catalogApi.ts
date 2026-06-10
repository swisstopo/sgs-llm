import { API3_BASE_URL } from '../config';
import type { AppLanguage } from '../i18n/i18n';
import { fetchJson } from './http';

/** A topic from the Swisstopo services list (e.g. `ech`, `bafu`). */
export interface CatalogTopic {
  id: string;
}

export interface CatalogLayerNode {
  kind: 'layer';
  id: number;
  label: string;
  layerBodId: string;
}

export interface CatalogFolderNode {
  kind: 'folder';
  id: number;
  label: string;
  children: CatalogNode[];
}

export type CatalogNode = CatalogLayerNode | CatalogFolderNode;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

export function parseTopics(raw: unknown): CatalogTopic[] {
  if (!isRecord(raw) || !Array.isArray(raw.topics)) {
    return [];
  }
  return raw.topics
    .filter((topic): topic is Record<string, unknown> => isRecord(topic))
    .filter((topic) => typeof topic.id === 'string' && topic.id.length > 0)
    .map((topic) => ({ id: topic.id as string }));
}

let nodeCounter = 0;

function parseNode(raw: unknown): CatalogNode | null {
  if (!isRecord(raw)) {
    return null;
  }
  // Leaves carry a layerBodId; skip non-production entries.
  if (typeof raw.layerBodId === 'string' && raw.layerBodId.length > 0) {
    if (typeof raw.staging === 'string' && raw.staging !== 'prod') {
      return null;
    }
    return {
      kind: 'layer',
      id: typeof raw.id === 'number' ? raw.id : ++nodeCounter,
      label: typeof raw.label === 'string' ? raw.label : raw.layerBodId,
      layerBodId: raw.layerBodId,
    };
  }
  if (Array.isArray(raw.children)) {
    const children = raw.children
      .map(parseNode)
      .filter((child): child is CatalogNode => child !== null);
    return {
      kind: 'folder',
      id: typeof raw.id === 'number' ? raw.id : ++nodeCounter,
      label: typeof raw.label === 'string' ? raw.label : '',
      children,
    };
  }
  return null;
}

/** Parses a CatalogServer response into the root folder node. */
export function parseCatalogTree(raw: unknown): CatalogFolderNode {
  const root =
    isRecord(raw) && isRecord(raw.results) && isRecord(raw.results.root)
      ? parseNode(raw.results.root)
      : null;
  if (root?.kind === 'folder') {
    return root;
  }
  return { kind: 'folder', id: 0, label: '', children: [] };
}

/** Lists the available topics (`GET /rest/services`). */
export async function fetchTopics(): Promise<CatalogTopic[]> {
  return parseTopics(await fetchJson(API3_BASE_URL));
}

/** Fetches the full layer catalog tree of a topic. */
export async function fetchCatalogTree(
  topic: string,
  lang: AppLanguage,
): Promise<CatalogFolderNode> {
  return parseCatalogTree(
    await fetchJson(`${API3_BASE_URL}/${encodeURIComponent(topic)}/CatalogServer?lang=${lang}`),
  );
}

/**
 * Prunes the tree to entries matching the query (case-insensitive label
 * match). A matching folder keeps its whole subtree; otherwise only
 * matching descendants survive. Returns null when nothing matches.
 */
export function filterCatalogTree(
  folder: CatalogFolderNode,
  query: string,
): CatalogFolderNode | null {
  const normalized = query.trim().toLowerCase();
  if (normalized.length === 0) {
    return folder;
  }
  const children = folder.children.flatMap((child): CatalogNode[] => {
    if (child.kind === 'layer') {
      return child.label.toLowerCase().includes(normalized) ? [child] : [];
    }
    if (child.label.toLowerCase().includes(normalized)) {
      return [child];
    }
    const filtered = filterCatalogTree(child, normalized);
    return filtered ? [filtered] : [];
  });
  return children.length > 0 ? { ...folder, children } : null;
}
