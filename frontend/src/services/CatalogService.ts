import { currentLanguage } from '../i18n/i18n';
import type { AppLanguage } from '../i18n/i18n';
import { fetchLayersConfig } from '../swisstopo/layersConfigApi';
import type { LayerConfig } from '../swisstopo/layersConfigApi';

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
}
