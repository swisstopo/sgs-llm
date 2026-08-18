// @vitest-environment jsdom

import { beforeAll, describe, expect, it } from 'vitest';
import { changeLanguage, initI18n } from '../../i18n/i18n';
import './sgs-layer-result-card';
import type { SgsLayerResultCard } from './sgs-layer-result-card';

beforeAll(async () => {
  await initI18n();
  await changeLanguage('en');
});

describe('sgs-layer-result-card', () => {
  it.each(['geojson', 'parquet'] as const)('offers %s layers on the map', async (format) => {
    const element = document.createElement('sgs-layer-result-card') as SgsLayerResultCard;
    element.layer = {
      id: 'layer',
      name: 'Layer',
      format,
      url: `https://data.test/layer.${format}`,
      geometry_type: 'point',
    };
    document.body.append(element);
    await element.updateComplete;

    expect(element.shadowRoot?.querySelector('button')).not.toBeNull();
    expect(element.shadowRoot?.querySelector('.unsupported')).toBeNull();
    expect(element.shadowRoot?.querySelector('.kind')?.textContent).toBe(
      'Personalized result layer',
    );
    element.remove();
  });
});
