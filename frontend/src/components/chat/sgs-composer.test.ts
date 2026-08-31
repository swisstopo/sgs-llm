// @vitest-environment jsdom

import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { changeLanguage, initI18n } from '../../i18n/i18n';
import './sgs-composer';
import type { SgsComposer } from './sgs-composer';

beforeAll(async () => {
  await initI18n();
  await changeLanguage('en');
});

beforeEach(() => {
  vi.useFakeTimers();
  // Monday 14:00 Europe/Zurich: Apertus is inside its service window.
  vi.setSystemTime(new Date('2026-08-31T12:00:00Z'));
});

afterEach(() => {
  document.body.replaceChildren();
  vi.useRealTimers();
});

describe('sgs-composer', () => {
  it('shows Claude, Mistral, and Apertus with its service window', async () => {
    const element = document.createElement('sgs-composer') as SgsComposer;
    document.body.append(element);
    await element.updateComplete;

    const trigger = element.shadowRoot?.querySelector('.model-trigger') as HTMLButtonElement;
    expect(trigger.textContent).toContain('Claude Sonnet 4.6');
    expect(trigger.querySelector('.model-logo svg')).not.toBeNull();

    trigger.click();
    await element.updateComplete;
    const options = [...(element.shadowRoot?.querySelectorAll('[role="option"]') ?? [])];
    expect(options).toHaveLength(3);
    expect(options[0]?.textContent).toContain('Claude Sonnet 4.6');
    expect(options[1]?.textContent).toContain('Ministral 3 14B');
    expect(options[2]?.textContent).toContain('Apertus 1.5 8B');
    expect(options[2]?.textContent).toContain('Monday–Friday · 06:40–19:00');
    expect(options[2]?.querySelector('[data-logo="swiss-flag"]')).not.toBeNull();
    expect(options.every((option) => option.querySelector('.model-logo svg'))).toBe(true);
    expect(element.shadowRoot?.textContent).not.toContain('Automatic');
    element.remove();
  });

  it('selects Apertus during its weekday service window', async () => {
    const element = document.createElement('sgs-composer') as SgsComposer;
    const listener = vi.fn();
    element.addEventListener('sgs-model-change', listener);
    document.body.append(element);
    await element.updateComplete;

    (element.shadowRoot?.querySelector('.model-trigger') as HTMLButtonElement).click();
    await element.updateComplete;
    (element.shadowRoot?.querySelector('[data-model="apertus"]') as HTMLButtonElement).click();
    await element.updateComplete;

    expect(element.model).toBe('apertus');
    expect(listener).toHaveBeenCalledOnce();
    expect((listener.mock.calls[0]?.[0] as CustomEvent).detail).toEqual({ model: 'apertus' });
    element.remove();
  });

  it('greys out Apertus and explains its schedule outside office hours', async () => {
    vi.setSystemTime(new Date('2026-08-30T12:00:00Z')); // Sunday.
    const element = document.createElement('sgs-composer') as SgsComposer;
    const listener = vi.fn();
    element.addEventListener('sgs-model-change', listener);
    document.body.append(element);
    await element.updateComplete;

    (element.shadowRoot?.querySelector('.model-trigger') as HTMLButtonElement).click();
    await element.updateComplete;
    const option = element.shadowRoot?.querySelector('[data-model="apertus"]') as HTMLButtonElement;
    expect(option.getAttribute('aria-disabled')).toBe('true');
    expect(option.getAttribute('aria-describedby')).toBe('apertus-availability-tooltip');
    expect(element.shadowRoot?.querySelector('[role="tooltip"]')?.textContent).toContain(
      'Apertus is currently offline',
    );

    option.click();
    expect(element.model).toBe('primary');
    expect(listener).not.toHaveBeenCalled();
    element.remove();
  });

  it('keeps a selected Apertus visible but blocks sending when its window closes', async () => {
    vi.setSystemTime(new Date('2026-08-31T16:59:50Z')); // 18:59:50 in Zurich.
    const element = document.createElement('sgs-composer') as SgsComposer;
    element.model = 'apertus';
    document.body.append(element);
    await element.updateComplete;

    expect(element.shadowRoot?.querySelector('.model-availability')).toBeNull();
    vi.advanceTimersByTime(30_000);
    await element.updateComplete;

    expect(element.shadowRoot?.querySelector('.model-availability')?.textContent).toContain(
      'Apertus is currently offline',
    );
    expect((element.shadowRoot?.querySelector('.submit') as HTMLButtonElement).disabled).toBe(true);
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
