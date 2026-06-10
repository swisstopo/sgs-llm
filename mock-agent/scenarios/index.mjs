import { floodScenario } from './flood.mjs';
import { solarScenario } from './solar.mjs';
import { parquetScenario } from './parquet.mjs';
import { defaultScenario } from './default.mjs';

const ROUTES = [
  {
    scenario: floodScenario,
    keywords: ['hochwasser', 'flood', 'crue', 'inondation', 'piena', 'alluvion', 'gefahr'],
  },
  {
    scenario: solarScenario,
    keywords: ['solar', 'photovolta', 'pv', 'dach', 'dächer', 'toit', 'tetti', 'roof'],
  },
  {
    scenario: parquetScenario,
    keywords: ['parquet'],
  },
];

/** Picks a scenario by keyword match on the user message. */
export function routeScenario(content, lang, baseUrl) {
  const normalized = content.toLowerCase();
  for (const route of ROUTES) {
    if (route.keywords.some((keyword) => normalized.includes(keyword))) {
      return route.scenario(lang, baseUrl);
    }
  }
  return defaultScenario(lang, baseUrl);
}
