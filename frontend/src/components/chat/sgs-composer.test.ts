// @vitest-environment jsdom

import { beforeAll, describe, expect, it, vi } from 'vitest';
import { changeLanguage, initI18n } from '../../i18n/i18n';
import './sgs-composer';
import type { SgsComposer } from './sgs-composer';

beforeAll(async () => {
  await initI18n();
  await changeLanguage('en');
});

describe('sgs-composer', () => {
  it('shows a branded custom list with only Claude and Mistral', async () => {
    const element = document.createElement('sgs-composer') as SgsComposer;
    document.body.append(element);
    await element.updateComplete;

    const trigger = element.shadowRoot?.querySelector('.model-trigger') as HTMLButtonElement;
    expect(trigger.textContent).toContain('Claude Sonnet 4.6');
    expect(trigger.querySelector('.model-logo svg')).not.toBeNull();

    trigger.click();
    await element.updateComplete;
    const options = [...(element.shadowRoot?.querySelectorAll('[role="option"]') ?? [])];
    expect(options).toHaveLength(2);
    expect(options.map((option) => option.textContent?.trim())).toEqual([
      'Claude Sonnet 4.6',
      'Ministral 3 14B',
    ]);
    expect(options.every((option) => option.querySelector('.model-logo svg'))).toBe(true);
    expect(element.shadowRoot?.textContent).not.toContain('Automatic');
    element.remove();
  });

  it('selects Mistral and emits the approved model role', async () => {
    const element = document.createElement('sgs-composer') as SgsComposer;
    const listener = vi.fn();
    element.addEventListener('sgs-model-change', listener);
    document.body.append(element);
    await element.updateComplete;

    (element.shadowRoot?.querySelector('.model-trigger') as HTMLButtonElement).click();
    await element.updateComplete;
    (element.shadowRoot?.querySelector('[data-model="secondary"]') as HTMLButtonElement).click();
    await element.updateComplete;

    expect(element.model).toBe('secondary');
    expect(listener).toHaveBeenCalledOnce();
    expect((listener.mock.calls[0]?.[0] as CustomEvent).detail).toEqual({ model: 'secondary' });
    expect(element.shadowRoot?.querySelector('.model-menu')).toBeNull();
    element.remove();
  });

  it('closes with Escape and locks model routing while a response is active', async () => {
    const element = document.createElement('sgs-composer') as SgsComposer;
    document.body.append(element);
    await element.updateComplete;

    const trigger = element.shadowRoot?.querySelector('.model-trigger') as HTMLButtonElement;
    trigger.click();
    await element.updateComplete;
    element.shadowRoot
      ?.querySelector('.model-control')
      ?.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
    await element.updateComplete;
    expect(element.shadowRoot?.querySelector('.model-menu')).toBeNull();

    element.busy = true;
    await element.updateComplete;
    expect(trigger.disabled).toBe(true);
    element.remove();
  });
});
