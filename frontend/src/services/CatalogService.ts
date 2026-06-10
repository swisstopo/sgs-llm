import { currentLanguage } from '../i18n/i18n';
import type { AppLanguage } from '../i18n/i18n';
import { fetchLayersConfig } from '../swisstopo/layersConfigApi';
import type { LayerConfig } from '../swisstopo/layersConfigApi';
import { fetchCatalogTree, fetchTopics } from '../swisstopo/catalogApi';
import type { CatalogFolderNode, CatalogTopic } from '../swisstopo/catalogApi';

/**
 * Caches Swisstopo layer catalog metadata (`layersConfig`) per language and
 * answers layer lookups for the map and the geocatalog tree.
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
}
