// @vitest-environment jsdom
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { changeLanguage, initI18n } from '../i18n/i18n';
import type { AdminRecord } from './types';
import './sgs-admin-app';

interface AdminElement extends HTMLElement {
  authenticated: boolean;
  loading: boolean;
  kind: string;
  from: string;
  to: string;
  records: AdminRecord[];
  updateComplete: Promise<boolean>;
}

beforeAll(async () => {
  await initI18n();
  await changeLanguage('en');
});
afterEach(() => {
  document.body.replaceChildren();
  vi.unstubAllGlobals();
});

const json = (value: unknown) => new Response(JSON.stringify(value));
async function setup() {
  const fetchMock = vi.fn().mockResolvedValueOnce(new Response(null, { status: 401 }));
  vi.stubGlobal('fetch', fetchMock);
  const element = document.createElement('sgs-admin-app') as unknown as AdminElement;
  document.body.append(element);
  await vi.waitFor(() => expect(element.loading).toBe(false));
  element.authenticated = true;
  element.kind = 'feedback';
  element.from = '2026-09-20';
  element.to = '2026-09-21';
  element.records = [
    { id: 'f1', category: 'bug', message: 'Wrong place', conversation_id: 'c1' },
    { id: 'f2', category: 'other', message: 'General feedback' },
  ];
  await element.updateComplete;
  const open = async () => {
    element.shadowRoot!.querySelector<HTMLButtonElement>('.record-row')!.click();
    await element.updateComplete;
  };
  const view = () =>
    [...element.shadowRoot!.querySelectorAll<HTMLButtonElement>('.drawer button')].find((button) =>
      button.textContent?.includes('Try again'),
    )!;
  return { element, fetchMock, view, open };
}

describe('feedback conversation in admin', () => {
  it('finds a linked conversation on a later page and shows it alongside the feedback', async () => {
    const { element, fetchMock, open } = await setup();
    fetchMock
      .mockResolvedValueOnce(
        json({ items: [{ conversation_id: 'unrelated' }], next_cursor: 'page+2' }),
      )
      .mockResolvedValueOnce(
        json({
          items: [
            {
              conversation_id: 'c1',
              turns: [
                {
                  message_id: 'm1',
                  model_id: 'model-1',
                  user_message: 'Where is Bern?',
                  assistant_markdown: '**Bern** is here.',
                  ts: '2026-09-21T12:00:00Z',
                },
              ],
            },
          ],
          next_cursor: null,
        }),
      );
    await open();
    await vi.waitFor(() => expect(element.shadowRoot?.textContent).toContain('Bern is here.'));
    expect(element.shadowRoot?.querySelector('.drawer')?.textContent).toContain('Wrong place');
    expect(element.shadowRoot?.querySelector('.drawer')?.textContent).toContain(
      '2026-09-20 – 2026-09-21',
    );
    expect(element.shadowRoot?.querySelector('.drawer')?.textContent).not.toContain(
      'Full conversation',
    );
    const diagnostics =
      element.shadowRoot!.querySelector<HTMLDetailsElement>('.technical-details')!;
    expect(diagnostics.open).toBe(false);
    expect(diagnostics.textContent).toContain('m1');
    expect(diagnostics.textContent).toContain('model-1');
    expect(element.shadowRoot!.querySelector('.feedback-conversation')?.textContent).not.toContain(
      'model-1',
    );
    expect(element.shadowRoot!.querySelector('.feedback-conversation')?.textContent).not.toContain(
      'Message ID',
    );
    expect(fetchMock.mock.calls[2]![0]).toContain('cursor=page%2B2');
    expect(fetchMock.mock.calls[2]![1]).toMatchObject({ credentials: 'include' });
  });

  it('explains a missing conversation and does not show links on general feedback', async () => {
    const { element, fetchMock, open } = await setup();
    fetchMock.mockResolvedValueOnce(json({ items: [], next_cursor: null }));
    await open();
    await vi.waitFor(() =>
      expect(element.shadowRoot?.textContent).toContain('try a wider date range'),
    );
    element.shadowRoot!.querySelector<HTMLButtonElement>('.drawer-head button')!.click();
    await element.updateComplete;
    element.shadowRoot!.querySelectorAll<HTMLButtonElement>('.record-row')[1]!.click();
    await element.updateComplete;
    expect(element.shadowRoot?.querySelector('.feedback-conversation')).toBeNull();
    expect(element.shadowRoot?.querySelector('.drawer')?.textContent).toContain(
      'No conversation attached',
    );
    expect(fetchMock).toHaveBeenCalledTimes(2);
    expect(element.shadowRoot?.querySelector('.drawer')?.textContent).not.toContain(
      'wider date range',
    );
  });

  it('supports retry after a lookup failure and aborts when the drawer closes', async () => {
    const { element, fetchMock, view, open } = await setup();
    fetchMock.mockResolvedValueOnce(new Response(null, { status: 503 }));
    await open();
    await vi.waitFor(() =>
      expect(element.shadowRoot?.textContent).toContain('could not be loaded'),
    );
    let resolve!: (response: Response) => void;
    fetchMock.mockReturnValueOnce(
      new Promise<Response>((done) => {
        resolve = done;
      }),
    );
    view().click();
    await element.updateComplete;
    const signal = fetchMock.mock.calls.at(-1)![1].signal as AbortSignal;
    element.shadowRoot!.querySelector<HTMLButtonElement>('.drawer-head button')!.click();
    expect(signal.aborted).toBe(true);
    resolve(
      json({
        items: [{ conversation_id: 'c1', turns: [{ user_message: 'Late result' }] }],
        next_cursor: null,
      }),
    );
    await element.updateComplete;
    expect(element.shadowRoot?.querySelector('.drawer')).toBeNull();
  });
  it('does not replace new feedback with the previous entry’s delayed conversation', async () => {
    const { element, fetchMock, open } = await setup();
    let resolve!: (response: Response) => void;
    fetchMock.mockReturnValueOnce(
      new Promise<Response>((done) => {
        resolve = done;
      }),
    );
    await open();
    expect(element.shadowRoot?.querySelector('.feedback-conversation')?.textContent).toContain(
      'Loading conversation',
    );
    const signal = fetchMock.mock.calls.at(-1)![1].signal as AbortSignal;
    element.shadowRoot!.querySelectorAll<HTMLButtonElement>('.record-row')[1]!.click();
    await element.updateComplete;
    expect(signal.aborted).toBe(true);
    resolve(
      json({
        items: [{ conversation_id: 'c1', turns: [{ user_message: 'Old question' }] }],
        next_cursor: null,
      }),
    );
    await new Promise((done) => setTimeout(done, 0));
    await element.updateComplete;
    expect(element.shadowRoot?.querySelector('.feedback-message')?.textContent).toBe(
      'General feedback',
    );
    expect(element.shadowRoot?.querySelector('.drawer')?.textContent).not.toContain('Old question');
  });
});
