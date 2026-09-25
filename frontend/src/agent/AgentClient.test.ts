import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AgentClient } from './AgentClient';
import { ChatService } from '../services/ChatService';
import type { ServerEvent } from '../protocol/v1';

vi.mock('../i18n/i18n', () => ({ currentLanguage: () => 'de' }));

class FakeWebSocket {
  static instances: FakeWebSocket[] = [];

  readyState = 0; // CONNECTING
  readonly sent: string[] = [];
  private listeners = new Map<string, ((event: never) => void)[]>();

  constructor(public url: string) {
    FakeWebSocket.instances.push(this);
  }

  addEventListener(type: string, listener: (event: never) => void): void {
    const list = this.listeners.get(type) ?? [];
    list.push(listener);
    this.listeners.set(type, list);
  }

  send(data: string): void {
    this.sent.push(data);
  }

  close(): void {
    this.simulateClose();
  }

  emit(type: string, event: unknown): void {
    for (const listener of this.listeners.get(type) ?? []) {
      (listener as (e: unknown) => void)(event);
    }
  }

  simulateOpen(): void {
    this.readyState = 1; // OPEN
    this.emit('open', {});
  }

  simulateMessage(data: unknown): void {
    this.emit('message', { data: JSON.stringify(data) });
  }

  simulateClose(): void {
    this.readyState = 3; // CLOSED
    this.emit('close', {});
  }
}

describe('AgentClient', () => {
  beforeEach(() => {
    vi.useFakeTimers();
    FakeWebSocket.instances = [];
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  function createClient(): AgentClient {
    return new AgentClient(() => 'ws://test/ws/v1', {
      webSocketFactory: (url) => new FakeWebSocket(url) as unknown as WebSocket,
      reconnectBaseMs: 100,
      reconnectMaxMs: 1000,
    });
  }

  it('reports status transitions and parses events', () => {
    const client = createClient();
    const statuses: string[] = [];
    const events: ServerEvent[] = [];
    client.status$.subscribe((status) => statuses.push(status));
    client.events$.subscribe((event) => events.push(event));

    client.connect();
    const socket = FakeWebSocket.instances[0]!;
    socket.simulateOpen();
    socket.simulateMessage({ type: 'done', message_id: 'm1' });
    socket.simulateMessage({ type: 'garbage', message_id: 'm1' });

    expect(statuses).toEqual(['closed', 'connecting', 'open']);
    expect(events).toEqual([{ type: 'done', message_id: 'm1' }]);
  });

  it('sends only while open', () => {
    const client = createClient();
    expect(client.send({ type: 'cancel', id: 'x' })).toBe(false);
    client.connect();
    const socket = FakeWebSocket.instances[0]!;
    socket.simulateOpen();
    expect(client.send({ type: 'cancel', id: 'x' })).toBe(true);
    expect(socket.sent).toEqual([JSON.stringify({ type: 'cancel', id: 'x' })]);
  });

  it('reconnects with exponential backoff after unexpected close', () => {
    const client = createClient();
    client.connect();
    const first = FakeWebSocket.instances[0]!;
    first.simulateOpen();
    first.simulateClose();
    expect(client.status).toBe('closed');

    vi.advanceTimersByTime(100);
    expect(FakeWebSocket.instances).toHaveLength(2);
    FakeWebSocket.instances[1]!.simulateClose();

    vi.advanceTimersByTime(199);
    expect(FakeWebSocket.instances).toHaveLength(2);
    vi.advanceTimersByTime(1);
    expect(FakeWebSocket.instances).toHaveLength(3);

    FakeWebSocket.instances[2]!.simulateOpen();
    expect(client.status).toBe('open');
  });

  it('sends one chat identity over replacement sockets and rotates it for a new chat', () => {
    const client = createClient();
    const chat = new ChatService(client);
    const first = FakeWebSocket.instances[0]!;
    first.simulateOpen();
    expect(chat.send('Where is Bern?')).toBe(true);
    const firstTurn = JSON.parse(first.sent[0]!);
    expect(firstTurn.conversation_id).toBeDefined();
    expect(firstTurn.conversation_id).toBe(chat.conversationId);
    first.simulateMessage({
      type: 'final',
      message_id: firstTurn.id,
      content_markdown: 'In Switzerland.',
    });
    first.simulateMessage({
      type: 'done',
      message_id: firstTurn.id,
      conversation_id: firstTurn.conversation_id,
    });
    first.simulateClose();
    expect(chat.send('while disconnected')).toBe(false);
    expect(chat.conversationId).toBe(firstTurn.conversation_id);

    vi.advanceTimersByTime(100);
    const second = FakeWebSocket.instances[1]!;
    second.simulateOpen();
    expect(chat.send('Show it on the map')).toBe(true);
    const secondTurn = JSON.parse(second.sent[0]!);
    expect(secondTurn.id).not.toBe(firstTurn.id);
    expect(secondTurn.conversation_id).toBe(firstTurn.conversation_id);
    expect(secondTurn.history).toEqual([
      { role: 'user', content: 'Where is Bern?' },
      { role: 'assistant', content: 'In Switzerland.' },
    ]);
    second.simulateMessage({
      type: 'done',
      message_id: secondTurn.id,
      conversation_id: secondTurn.conversation_id,
    });
    expect(chat.conversationId).toBe(firstTurn.conversation_id);

    chat.clear();
    expect(chat.conversationId).toBeUndefined();
    expect(chat.send('A new conversation')).toBe(true);
    const newTurn = JSON.parse(second.sent[1]!);
    expect(newTurn.conversation_id).toBe(chat.conversationId);
    expect(newTurn.conversation_id).not.toBe(firstTurn.conversation_id);
    expect(newTurn.history).toEqual([]);
    client.close();
  });

  it('does not reconnect after an explicit close', () => {
    const client = createClient();
    client.connect();
    FakeWebSocket.instances[0]!.simulateOpen();
    client.close();
    vi.advanceTimersByTime(5000);
    expect(FakeWebSocket.instances).toHaveLength(1);
    expect(client.status).toBe('closed');
  });
});
