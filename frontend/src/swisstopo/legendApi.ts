import { API3_BASE_URL } from '../config';
import type { AppLanguage } from '../i18n/i18n';

/**
 * Fetches the legend HTML fragment for a layer. The returned HTML is
 * untrusted and must only be rendered inside a sandboxed iframe.
 */
export async function fetchLegendHtml(layerId: string, lang: AppLanguage): Promise<string> {
  const response = await fetch(
    `${API3_BASE_URL}/api/MapServer/${encodeURIComponent(layerId)}/legend?lang=${lang}`,
  );
  if (!response.ok) {
    throw new Error(`legend request failed: ${response.status}`);
  }
  return response.text();
}
