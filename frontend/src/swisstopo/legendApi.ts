import { API3_BASE_URL } from '../config';
import type { AppLanguage } from '../i18n/i18n';
import { fetchText } from './http';

/**
 * Fetches the legend HTML fragment for a layer. The returned HTML is
 * untrusted and must only be rendered inside a sandboxed iframe.
 */
export async function fetchLegendHtml(layerId: string, lang: AppLanguage): Promise<string> {
  return fetchText(
    `${API3_BASE_URL}/api/MapServer/${encodeURIComponent(layerId)}/legend?lang=${lang}`,
  );
}
