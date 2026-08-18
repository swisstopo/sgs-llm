// @vitest-environment jsdom

import { beforeAll, describe, expect, it, vi } from 'vitest';
import { changeLanguage, initI18n } from '../../i18n/i18n';
import './sgs-catalog-layer-card';
import type { SgsCatalogLayerCard } from './sgs-catalog-layer-card';

beforeAll(async () => {
  await initI18n();
  await changeLanguage('en');
});

describe('sgs-catalog-layer-card', () => {
  it('offers official tiles on the map and keeps the focus bbox', async () => {
    const element = document.createElement('sgs-catalog-layer-card') as SgsCatalogLayerCard;
    element.layer = { id: 'ch.test.tiles', name: 'Flood layer', opacity: 0.7 };
    element.focusBBox = [7.2, 46.8, 7.8, 47.2];
    const listener = vi.fn();
    element.addEventListener('sgs-add-catalog-layer', listener);
    document.body.append(element);
    await element.updateComplete;

    expect(element.shadowRoot?.querySelector('.kind')?.textContent).toBe('Official map layer');

    (element.shadowRoot?.querySelector('button') as HTMLButtonElement).click();

    expect(listener).toHaveBeenCalledOnce();
    const event = listener.mock.calls[0]?.[0] as CustomEvent;
    expect(event.detail).toEqual({
      layer: element.layer,
      focusBBox: element.focusBBox,
    });
    element.remove();
  });

  it('opens the existing layer-details dialog', async () => {
    const element = document.createElement('sgs-catalog-layer-card') as SgsCatalogLayerCard;
    element.layer = { id: 'ch.test.tiles', name: 'Flood layer' };
    const listener = vi.fn();
    element.addEventListener('sgs-open-catalog-layer', listener);
    document.body.append(element);
    await element.updateComplete;

    (element.shadowRoot?.querySelector('button.secondary') as HTMLButtonElement).click();

    const event = listener.mock.calls[0]?.[0] as CustomEvent;
    expect(event.detail).toEqual({
      id: 'ch.test.tiles',
      label: 'Flood layer',
    });
    element.remove();
  });

  it('removes an official layer that is already on the map', async () => {
    const element = document.createElement('sgs-catalog-layer-card') as SgsCatalogLayerCard;
    element.layer = { id: 'ch.test.tiles', name: 'Flood layer' };
    element.added = true;
    const listener = vi.fn();
    element.addEventListener('sgs-remove-catalog-layer', listener);
    document.body.append(element);
    await element.updateComplete;

    (element.shadowRoot?.querySelector('button') as HTMLButtonElement).click();

    const event = listener.mock.calls[0]?.[0] as CustomEvent;
    expect(event.detail).toEqual({ id: 'ch.test.tiles' });
    element.remove();
  });
});
