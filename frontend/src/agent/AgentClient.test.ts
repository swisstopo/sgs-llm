import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { AgentClient } from './AgentClient';
import type { ServerEvent } from '../protocol/v1';

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
