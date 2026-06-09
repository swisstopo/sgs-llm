import { currentLanguage } from '../i18n/i18n';
import type { AppLanguage } from '../i18n/i18n';
import { fetchLayersConfig } from '../swisstopo/layersConfigApi';
import type { LayerConfig } from '../swisstopo/layersConfigApi';
import { isWmtsDisplayable } from '../swisstopo/wmts';
import { loadLayerTree } from '../layers/loadLayerTree';
import { searchLayers, searchLocations } from '../swisstopo/searchApi';
import type { LayerSearchResult, LocationSearchResult } from '../swisstopo/searchApi';

export interface CatalogEntry {
  id: string;
  label: string;
  displayable: boolean;
}

export interface CatalogGroup {
  id: string;
  label: string;
  entries: CatalogEntry[];
}

/**
 * Caches Swisstopo layer catalog metadata (`layersConfig`) per language and
 * answers layer lookups for the map, the catalog tree, and search results.
 */
export class CatalogService {
  private readonly configCache = new Map<AppLanguage, Promise<Map<string, LayerConfig>>>();

  /** The full layer metadata catalog for a language (fetched once, cached). */
  getConfig(lang: AppLanguage = currentLanguage()): Promise<Map<string, LayerConfig>> {
    let cached = this.configCache.get(lang);
    if (!cached) {
      cached = fetchLayersConfig(lang).catch((error: unknown) => {
        // Do not cache failures; allow a retry on the next call.
        this.configCache.delete(lang);
        throw error;
      });
      this.configCache.set(lang, cached);
    }
    return cached;
  }

  async getLayer(
    id: string,
    lang: AppLanguage = currentLanguage(),
  ): Promise<LayerConfig | undefined> {
    return (await this.getConfig(lang)).get(id);
  }

  /**
   * The curated layer tree (layers/layertree.json5) hydrated with labels and
   * displayability from layersConfig. Unknown ids are dropped.
   */
  async getTree(lang: AppLanguage = currentLanguage()): Promise<CatalogGroup[]> {
    const config = await this.getConfig(lang);
    return loadLayerTree().map((group) => ({
      id: group.id,
      label: group.label[lang],
      entries: group.children.flatMap((id) => {
        const layer = config.get(id);
        if (!layer) {
          console.warn(`Curated layer ${id} not found in layersConfig`);
          return [];
        }
        return [{ id, label: layer.label, displayable: isWmtsDisplayable(layer) }];
      }),
    }));
  }

  /** Full-catalog layer search, annotated with WMTS displayability. */
  async searchLayers(
    query: string,
    lang: AppLanguage = currentLanguage(),
  ): Promise<(LayerSearchResult & { displayable: boolean })[]> {
    const [results, config] = await Promise.all([searchLayers(query, lang), this.getConfig(lang)]);
    return results.map((result) => {
      const layer = config.get(result.layerId);
      return { ...result, displayable: layer !== undefined && isWmtsDisplayable(layer) };
    });
  }

  searchLocations(query: string): Promise<LocationSearchResult[]> {
    return searchLocations(query);
  }
}
