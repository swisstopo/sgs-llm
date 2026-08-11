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
  it('offers map rendering for a live MVT layer and warns when retrieval was incomplete', async () => {
    const card = document.createElement('sgs-layer-result-card') as SgsLayerResultCard;
    card.layer = {
      id: 'large',
      name: 'Large roads',
      format: 'mvt',
      url: '/data/tiles/token/{z}/{x}/{y}.mvt',
      geometry_type: 'line',
      feature_count: 100_000,
      truncated: true,
      min_zoom: 0,
      max_zoom: 16,
    };
    document.body.append(card);
    await card.updateComplete;

    expect(card.shadowRoot?.querySelector('button')).not.toBeNull();
    expect(card.shadowRoot?.querySelector('[role="alert"]')?.textContent).toContain('incomplete');
    expect(card.shadowRoot?.querySelector('a')).toBeNull();
    card.remove();
  });

  it('explains an expired MVT capability instead of offering a broken map action', async () => {
    const card = document.createElement('sgs-layer-result-card') as SgsLayerResultCard;
    card.layer = {
      id: 'expired',
      name: 'Expired layer',
      format: 'mvt',
      url: '/data/tiles/token/{z}/{x}/{y}.mvt',
      url_expires_at: '2000-01-01T00:00:00Z',
      geometry_type: 'line',
      min_zoom: 0,
      max_zoom: 16,
    };
    document.body.append(card);
    await card.updateComplete;

    expect(card.shadowRoot?.querySelector('button')).toBeNull();
    expect(card.shadowRoot?.textContent).toContain('temporary map layer has expired');
    expect(card.shadowRoot?.textContent).toContain('regenerate');
    card.remove();
  });
});
