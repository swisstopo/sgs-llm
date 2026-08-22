// @vitest-environment jsdom

import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { changeLanguage, initI18n } from '../../i18n/i18n';
import './sgs-chat-onboarding-dialog';
import type { SgsChatOnboardingDialog } from './sgs-chat-onboarding-dialog';

beforeAll(async () => {
  HTMLDialogElement.prototype.showModal = vi.fn(function (this: HTMLDialogElement) {
    this.open = true;
  });
  await initI18n();
  await changeLanguage('en');
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('sgs-chat-onboarding-dialog', () => {
  it('opens modally and accepts only through the primary action', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: 'entry-id' }), {
        status: 201,
        headers: { 'content-type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);
    const element = document.createElement('sgs-chat-onboarding-dialog') as SgsChatOnboardingDialog;
    const accept = vi.fn();
    element.addEventListener('sgs-accept', accept);
    document.body.append(element);
    await element.updateComplete;

    const dialog = element.shadowRoot?.querySelector('dialog');
    expect(dialog?.open).toBe(true);
    expect(dialog?.getAttribute('aria-labelledby')).toBe('chat-onboarding-title');
    expect(element.shadowRoot?.querySelector('h2')?.textContent).toContain('Welcome to SGS LLM');
    expect(element.shadowRoot?.textContent).toContain('experimental prototype chatbot');
    expect(element.shadowRoot?.querySelectorAll('form select')).toHaveLength(3);

    const selects = element.shadowRoot?.querySelectorAll('form select') ?? [];
    (selects[0] as HTMLSelectElement).value = 'public_administration';
    (selects[1] as HTMLSelectElement).value = 'advanced';
    (selects[2] as HTMLSelectElement).value = 'professional_analysis';
    element.shadowRoot
      ?.querySelector('form')
      ?.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));

    await vi.waitFor(() => expect(accept).toHaveBeenCalledOnce());
    expect(JSON.parse(fetchMock.mock.calls[0]?.[1]?.body as string)).toMatchObject({
      type: 'onboarding',
      user_group: 'public_administration',
      geodata_experience: 'advanced',
      intended_use: 'professional_analysis',
      consent_version: 'v2',
    });
    element.remove();
  });

  it('keeps the modal open when the database does not confirm the write', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(null, { status: 503 })));
    const element = document.createElement('sgs-chat-onboarding-dialog') as SgsChatOnboardingDialog;
    const accept = vi.fn();
    element.addEventListener('sgs-accept', accept);
    document.body.append(element);
    await element.updateComplete;

    const selects = element.shadowRoot?.querySelectorAll('form select') ?? [];
    (selects[0] as HTMLSelectElement).value = 'private_individual';
    (selects[1] as HTMLSelectElement).value = 'new';
    (selects[2] as HTMLSelectElement).value = 'learning_other';

    element.shadowRoot
      ?.querySelector('form')
      ?.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));

    await vi.waitFor(() =>
      expect(element.shadowRoot?.querySelector('[role="alert"]')).not.toBeNull(),
    );
    expect(accept).not.toHaveBeenCalled();
    element.remove();
  });

  it('cannot be closed with a top action or Escape', async () => {
    const element = document.createElement('sgs-chat-onboarding-dialog') as SgsChatOnboardingDialog;
    document.body.append(element);
    await element.updateComplete;

    expect(element.shadowRoot?.querySelector('.close')).toBeNull();
    const dialog = element.shadowRoot?.querySelector('dialog') as HTMLDialogElement;
    const cancel = new Event('cancel', { cancelable: true });
    expect(dialog.dispatchEvent(cancel)).toBe(false);
    expect(cancel.defaultPrevented).toBe(true);
    expect(dialog.open).toBe(true);
    element.remove();
  });

  it('treats every survey question as optional and omits unanswered ones', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ id: 'entry-id' }), {
        status: 201,
        headers: { 'content-type': 'application/json' },
      }),
    );
    vi.stubGlobal('fetch', fetchMock);
    const element = document.createElement('sgs-chat-onboarding-dialog') as SgsChatOnboardingDialog;
    const accept = vi.fn();
    element.addEventListener('sgs-accept', accept);
    document.body.append(element);
    await element.updateComplete;

    const form = element.shadowRoot?.querySelector('form') as HTMLFormElement;
    const selects = element.shadowRoot?.querySelectorAll('form select') ?? [];
    expect([...selects].every((select) => !(select as HTMLSelectElement).required)).toBe(true);
    expect(element.shadowRoot?.querySelectorAll('label .optional')).toHaveLength(3);
    expect(form.checkValidity()).toBe(true);

    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await vi.waitFor(() => expect(accept).toHaveBeenCalledOnce());
    expect(JSON.parse(fetchMock.mock.calls[0]?.[1]?.body as string)).toEqual({
      type: 'onboarding',
      consent_version: 'v2',
      lang: 'en',
    });

    (selects[1] as HTMLSelectElement).value = 'occasional';
    form.dispatchEvent(new SubmitEvent('submit', { bubbles: true, cancelable: true }));
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(JSON.parse(fetchMock.mock.calls[1]?.[1]?.body as string)).toEqual({
      type: 'onboarding',
      geodata_experience: 'occasional',
      consent_version: 'v2',
      lang: 'en',
    });
    element.remove();
  });

  it('changes language without changing the selected answer ids', async () => {
    const element = document.createElement('sgs-chat-onboarding-dialog') as SgsChatOnboardingDialog;
    document.body.append(element);
    await element.updateComplete;

    const answers = element.shadowRoot?.querySelectorAll('form select') ?? [];
    (answers[0] as HTMLSelectElement).value = 'public_administration';
    answers[0]?.dispatchEvent(new Event('change', { bubbles: true }));
    (answers[1] as HTMLSelectElement).value = 'advanced';
    answers[1]?.dispatchEvent(new Event('change', { bubbles: true }));
    (answers[2] as HTMLSelectElement).value = 'professional_analysis';
    answers[2]?.dispatchEvent(new Event('change', { bubbles: true }));

    const language = element.shadowRoot?.querySelector('.language-select') as HTMLSelectElement;
    expect(language.value).toBe('en');
    language.value = 'de';
    language.dispatchEvent(new Event('change', { bubbles: true }));

    await vi.waitFor(() =>
      expect(element.shadowRoot?.querySelector('h2')?.textContent).toContain('Willkommen'),
    );
    const translatedAnswers = element.shadowRoot?.querySelectorAll('form select') ?? [];
    expect([...translatedAnswers].map((select) => (select as HTMLSelectElement).value)).toEqual([
      'public_administration',
      'advanced',
      'professional_analysis',
    ]);
    expect(translatedAnswers[0]?.textContent).toContain('Öffentliche Verwaltung');
    expect(element.shadowRoot?.querySelector('a')?.href).toBe(
      'https://www.admin.ch/de/rechtliches',
    );
    expect(element.shadowRoot?.querySelector('a')?.lang).toBe('de');
    expect(element.shadowRoot?.querySelector('a')?.textContent).toContain('Rechtliches');

    await changeLanguage('en');
    element.remove();
  });
});
