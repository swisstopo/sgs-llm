import { BehaviorSubject, Subject } from 'rxjs';
import type { Observable } from 'rxjs';
import { parseServerEvent } from '../protocol/v1';
import type { ClientEvent, ServerEvent } from '../protocol/v1';

export type ConnectionStatus = 'connecting' | 'open' | 'closed';

export interface AgentClientOptions {
  /** WebSocket constructor, injectable for tests. */
  webSocketFactory?: (url: string) => WebSocket;
  /** Initial reconnect delay in ms (doubles per attempt). */
  reconnectBaseMs?: number;
  /** Upper bound for the reconnect delay in ms. */
  reconnectMaxMs?: number;
}

/**
 * WebSocket client for the agent protocol v1: maintains the connection with
 * exponential-backoff reconnect, parses incoming frames, and exposes them as
 * an event stream.
 */
export class AgentClient {
  private readonly statusSubject = new BehaviorSubject<ConnectionStatus>('closed');
  private readonly eventsSubject = new Subject<ServerEvent>();

  private socket?: WebSocket;
  private reconnectAttempts = 0;
  private reconnectHandle?: ReturnType<typeof setTimeout>;
  private closedByUser = false;

  private readonly webSocketFactory: (url: string) => WebSocket;
  private readonly reconnectBaseMs: number;
  private readonly reconnectMaxMs: number;

  constructor(
    private readonly urlProvider: () => string,
    options: AgentClientOptions = {},
  ) {
    this.webSocketFactory = options.webSocketFactory ?? ((url) => new WebSocket(url));
    this.reconnectBaseMs = options.reconnectBaseMs ?? 500;
    this.reconnectMaxMs = options.reconnectMaxMs ?? 10_000;
  }

  get status$(): Observable<ConnectionStatus> {
    return this.statusSubject.asObservable();
  }

  get status(): ConnectionStatus {
    return this.statusSubject.value;
  }

  get events$(): Observable<ServerEvent> {
    return this.eventsSubject.asObservable();
  }

  connect(): void {
    if (this.socket && this.socket.readyState <= WebSocket.OPEN) {
      return;
    }
    this.closedByUser = false;
    this.open();
  }

  /** Sends a client event; returns false when the connection is not open. */
  send(event: ClientEvent): boolean {
    if (!this.socket || this.socket.readyState !== WebSocket.OPEN) {
      return false;
    }
    this.socket.send(JSON.stringify(event));
    return true;
  }

  close(): void {
    this.closedByUser = true;
    clearTimeout(this.reconnectHandle);
    this.socket?.close();
    this.socket = undefined;
    this.statusSubject.next('closed');
  }

  private open(): void {
    this.statusSubject.next('connecting');
    let socket: WebSocket;
    try {
      socket = this.webSocketFactory(this.urlProvider());
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.socket = socket;

    socket.addEventListener('open', () => {
      if (socket !== this.socket) {
        return;
      }
      this.reconnectAttempts = 0;
      this.statusSubject.next('open');
    });

    socket.addEventListener('message', (message: MessageEvent) => {
      if (socket !== this.socket || typeof message.data !== 'string') {
        return;
      }
      const event = parseServerEvent(message.data);
      if (event) {
        this.eventsSubject.next(event);
      }
    });

    socket.addEventListener('close', () => {
      if (socket !== this.socket) {
        return;
      }
      this.socket = undefined;
      this.statusSubject.next('closed');
      if (!this.closedByUser) {
        this.scheduleReconnect();
      }
    });

    socket.addEventListener('error', () => {
      // The subsequent close event drives reconnect handling.
    });
  }

  private scheduleReconnect(): void {
    const delay = Math.min(this.reconnectBaseMs * 2 ** this.reconnectAttempts, this.reconnectMaxMs);
    this.reconnectAttempts += 1;
    clearTimeout(this.reconnectHandle);
    this.reconnectHandle = setTimeout(() => this.open(), delay);
  }
}
