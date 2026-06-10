import { beforeEach, describe, expect, it, vi } from 'vitest';
import { Subject } from 'rxjs';
import { ChatService } from './ChatService';
import type { AgentClient } from '../agent/AgentClient';
import type { ClientEvent, ServerEvent } from '../protocol/v1';

vi.mock('../i18n/i18n', () => ({
  currentLanguage: () => 'de',
}));

class FakeAgentClient {
  readonly events$ = new Subject<ServerEvent>();
  readonly sent: ClientEvent[] = [];
  sendResult = true;

  connect(): void {}

  send(event: ClientEvent): boolean {
    if (!this.sendResult) {
      return false;
    }
    this.sent.push(event);
    return true;
  }
}

describe('ChatService', () => {
  let client: FakeAgentClient;
  let service: ChatService;

  beforeEach(() => {
    client = new FakeAgentClient();
    service = new ChatService(client as unknown as AgentClient);
  });

  function lastUserMessageId(): string {
    const event = client.sent.at(-1);
    if (event?.type !== 'user_message') {
      throw new Error('no user message sent');
    }
    return event.id;
  }

  it('appends user + streaming assistant messages on send', () => {
    expect(service.send('Hochwasser im Wallis?')).toBe(true);
    expect(service.messages).toHaveLength(2);
    expect(service.messages[0]).toMatchObject({ role: 'user', content: 'Hochwasser im Wallis?' });
    expect(service.messages[1]).toMatchObject({ role: 'assistant', status: 'streaming' });
    expect(service.busy).toBe(true);
  });

  it('rejects empty input, double-send while busy, and closed connections', () => {
    expect(service.send('   ')).toBe(false);
    service.send('first');
    expect(service.send('second while busy')).toBe(false);
    client.sendResult = false;
    expect(service.busy).toBe(true);
  });

  it('tracks progress steps by step_id', () => {
    service.send('test');
    const id = lastUserMessageId();
    client.events$.next({
      type: 'intermediate',
      message_id: id,
      step_id: 's1',
      status: 'started',
      label: 'Suche Layer …',
    });
    client.events$.next({
      type: 'intermediate',
      message_id: id,
      step_id: 's1',
      status: 'finished',
      label: 'Layer gefunden',
    });
    const assistant = service.messages[1];
    expect(assistant).toMatchObject({
      role: 'assistant',
      steps: [{ stepId: 's1', status: 'finished', label: 'Layer gefunden' }],
    });
  });

  it('completes on final + done and clears busy', () => {
    service.send('test');
    const id = lastUserMessageId();
    client.events$.next({
      type: 'final',
      message_id: id,
      content_markdown: '## Antwort',
      layers: [
        {
          id: 'l1',
          name: 'Zonen',
          format: 'geojson',
          url: 'http://localhost/x.geojson',
          geometry_type: 'polygon',
        },
      ],
    });
    client.events$.next({ type: 'done', message_id: id });
    expect(service.messages[1]).toMatchObject({
      status: 'complete',
      markdown: '## Antwort',
      layers: [{ id: 'l1' }],
    });
    expect(service.busy).toBe(false);
  });

  it('marks errors and cancellations', () => {
    service.send('test');
    const id = lastUserMessageId();
    client.events$.next({ type: 'error', message_id: id, code: 'cancelled', message: 'stopped' });
    client.events$.next({ type: 'done', message_id: id });
    expect(service.messages[1]).toMatchObject({ status: 'cancelled', errorCode: 'cancelled' });
    expect(service.busy).toBe(false);
  });

  it('treats done without final/error as an internal error', () => {
    service.send('test');
    client.events$.next({ type: 'done', message_id: lastUserMessageId() });
    expect(service.messages[1]).toMatchObject({ status: 'error', errorCode: 'internal' });
  });

  it('sends cancel for the streaming exchange', () => {
    service.send('test');
    const id = lastUserMessageId();
    service.cancel();
    expect(client.sent.at(-1)).toEqual({ type: 'cancel', id });
  });

  it('clears messages and busy, cancelling any in-flight exchange', () => {
    service.send('test');
    const id = lastUserMessageId();
    service.clear();
    expect(client.sent.at(-1)).toEqual({ type: 'cancel', id });
    expect(service.messages).toEqual([]);
    expect(service.busy).toBe(false);
  });

  it('clears an idle conversation without sending a cancel', () => {
    service.send('first');
    const id = lastUserMessageId();
    client.events$.next({ type: 'final', message_id: id, content_markdown: 'answer one' });
    client.events$.next({ type: 'done', message_id: id });
    const sentBefore = client.sent.length;
    service.clear();
    expect(client.sent).toHaveLength(sentBefore);
    expect(service.messages).toEqual([]);
    expect(service.busy).toBe(false);
  });

  it('builds history from completed exchanges only', () => {
    service.send('first');
    const id = lastUserMessageId();
    client.events$.next({ type: 'final', message_id: id, content_markdown: 'answer one' });
    client.events$.next({ type: 'done', message_id: id });
    service.send('second');
    const event = client.sent.at(-1);
    expect(event?.type).toBe('user_message');
    if (event?.type === 'user_message') {
      expect(event.history).toEqual([
        { role: 'user', content: 'first' },
        { role: 'assistant', content: 'answer one' },
      ]);
      expect(event.lang).toBe('de');
    }
  });
});
