// @vitest-environment jsdom
import { ContextProvider } from '@lit/context';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { Subject } from 'rxjs';
import { chatServiceContext } from '../../context';
import { ChatService } from '../../services/ChatService';
import type { AgentClient } from '../../agent/AgentClient';
import { changeLanguage, initI18n } from '../../i18n/i18n';
import type { ClientEvent, ServerEvent } from '../../protocol/v1';
import './sgs-feedback-panel';

beforeAll(async () => {
  await initI18n();
  await changeLanguage('en');
});
afterEach(() => {
  document.body.replaceChildren();
  vi.unstubAllGlobals();
});

async function setup() {
  const events = new Subject<ServerEvent>();
  const sent: ClientEvent[] = [];
  const chat = new ChatService({
    connect() {},
    events$: events,
    send(event: ClientEvent) {
      sent.push(event);
      return true;
    },
  } as unknown as AgentClient);
  const host = document.createElement('div');
  new ContextProvider(host, { context: chatServiceContext, initialValue: chat });
  document.body.append(host);
  const panel = document.createElement('sgs-feedback-panel');
  host.append(panel);
  await panel.updateComplete;
  return { chat, events, sent, panel };
}

describe('feedback conversation link', () => {
  it('submits the current server id and leaves a new empty chat unlinked', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetchMock);
    const { chat, events, sent, panel } = await setup();
    chat.send('Where is Bern?');
    events.next({ type: 'done', message_id: sent[0]!.id, conversation_id: 'thread-1' });
    await panel.updateComplete;
    expect(panel.shadowRoot?.textContent).toContain('Your current conversation will be included');
    panel.shadowRoot!.querySelector('textarea')!.value = 'The answer needs detail';
    panel.shadowRoot!.querySelector<HTMLButtonElement>('button.submit')!.click();
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    expect(JSON.parse(fetchMock.mock.calls[0]![1].body)).toMatchObject({
      conversation_id: 'thread-1',
      message: 'The answer needs detail',
    });
    panel.remove();
    chat.clear();
    const next = document.createElement('sgs-feedback-panel');
    document.querySelector('div')!.append(next);
    await next.updateComplete;
    expect(next.shadowRoot?.textContent).not.toContain(
      'Your current conversation will be included',
    );
    next.shadowRoot!.querySelector('textarea')!.value = 'General feedback';
    next.shadowRoot!.querySelector<HTMLButtonElement>('button.submit')!.click();
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
    expect(JSON.parse(fetchMock.mock.calls[1]![1].body)).not.toHaveProperty('conversation_id');
  });

  it('keeps the text and conversation reference when a request fails and is retried', async () => {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 503 }))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetchMock);
    const { chat, events, sent, panel } = await setup();
    chat.send('A question');
    events.next({ type: 'done', message_id: sent[0]!.id, conversation_id: 'thread-2' });
    panel.shadowRoot!.querySelector('textarea')!.value = 'Please keep this text';
    panel.shadowRoot!.querySelector<HTMLButtonElement>('button.submit')!.click();
    await vi.waitFor(() => expect(panel.shadowRoot?.textContent).toContain('could not be sent'));
    expect(panel.shadowRoot!.querySelector('textarea')!.value).toBe('Please keep this text');
    panel.shadowRoot!.querySelector<HTMLButtonElement>('button.submit')!.click();
    await vi.waitFor(() => expect(panel.shadowRoot?.textContent).toContain('Thank you'));
    expect(fetchMock.mock.calls[0]![1].body).toBe(fetchMock.mock.calls[1]![1].body);
    vi.restoreAllMocks();
  });
});
