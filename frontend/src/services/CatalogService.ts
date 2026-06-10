import { currentLanguage } from '../i18n/i18n';
import type { AppLanguage } from '../i18n/i18n';
import { fetchLayersConfig } from '../swisstopo/layersConfigApi';
import type { LayerConfig } from '../swisstopo/layersConfigApi';
import { isWmtsDisplayable } from '../swisstopo/wmts';
import { fetchCatalogTree, fetchTopics } from '../swisstopo/catalogApi';
import type { CatalogFolderNode, CatalogTopic } from '../swisstopo/catalogApi';
import { searchLayers, searchLocations } from '../swisstopo/searchApi';
import type {
  LayerSearchOptions,
  LayerSearchResult,
  LocationSearchOptions,
  LocationSearchResult,
} from '../swisstopo/searchApi';

/**
 * Caches Swisstopo layer catalog metadata (`layersConfig`) per language and
 * answers layer lookups for the map, the catalog tree, and search results.
 */
export class CatalogService {
  private readonly configCache = new Map<AppLanguage, Promise<Map<string, LayerConfig>>>();
  private readonly catalogCache = new Map<string, Promise<CatalogFolderNode>>();
  private topicsCache?: Promise<CatalogTopic[]>;

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

  /** Available geocatalog topics (fetched once, cached). */
  getTopics(): Promise<CatalogTopic[]> {
    this.topicsCache ??= fetchTopics().catch((error: unknown) => {
      this.topicsCache = undefined;
      throw error;
    });
    return this.topicsCache;
  }

  /** Official geocatalog tree of a topic (cached per topic + language). */
  getCatalogTree(topic: string, lang: AppLanguage = currentLanguage()): Promise<CatalogFolderNode> {
    const key = `${topic}/${lang}`;
    let cached = this.catalogCache.get(key);
    if (!cached) {
      cached = fetchCatalogTree(topic, lang).catch((error: unknown) => {
        this.catalogCache.delete(key);
        throw error;
      });
      this.catalogCache.set(key, cached);
    }
    return cached;
  }

  /** Full-catalog layer search, annotated with WMTS displayability. */
  async searchLayers(
    query: string,
    lang: AppLanguage = currentLanguage(),
    options: LayerSearchOptions = {},
  ): Promise<(LayerSearchResult & { displayable: boolean })[]> {
    const [results, config] = await Promise.all([
      searchLayers(query, lang, options),
      this.getConfig(lang),
    ]);
    return results.map((result) => {
      const layer = config.get(result.layerId);
      return { ...result, displayable: layer !== undefined && isWmtsDisplayable(layer) };
    });
  }

  searchLocations(
    query: string,
    options: LocationSearchOptions = {},
  ): Promise<LocationSearchResult[]> {
    return searchLocations(query, options);
  }
}
