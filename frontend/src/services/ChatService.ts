import { BehaviorSubject } from 'rxjs';
import type { Observable } from 'rxjs';
import type { AgentClient } from '../agent/AgentClient';
import type { ErrorCode, HistoryEntry, LayerSpec, MapContext, ServerEvent } from '../protocol/v1';
import { currentLanguage } from '../i18n/i18n';

export interface ProgressStep {
  stepId: string;
  status: 'started' | 'finished' | 'failed';
  label: string;
  detail?: string;
}

export interface UserChatMessage {
  role: 'user';
  id: string;
  content: string;
}

export interface AssistantChatMessage {
  role: 'assistant';
  /** Correlates with the triggering user message id (`message_id`). */
  id: string;
  status: 'streaming' | 'complete' | 'error' | 'cancelled';
  steps: ProgressStep[];
  markdown?: string;
  layers?: LayerSpec[];
  errorCode?: ErrorCode;
  errorMessage?: string;
}

export type ChatMessage = UserChatMessage | AssistantChatMessage;

/** Number of prior exchanges sent along as conversation history. */
const HISTORY_LIMIT = 10;

/**
 * Chat state machine: turns the agent's streamed protocol events into the
 * ordered message list rendered by the chat panel.
 */
export class ChatService {
  private readonly messagesSubject = new BehaviorSubject<ChatMessage[]>([]);
  private readonly busySubject = new BehaviorSubject<boolean>(false);

  constructor(
    private readonly client: AgentClient,
    private readonly mapContextProvider?: () => MapContext | undefined,
  ) {
    client.events$.subscribe((event) => this.onEvent(event));
    client.connect();
  }

  get messages$(): Observable<ChatMessage[]> {
    return this.messagesSubject.asObservable();
  }

  get messages(): ChatMessage[] {
    return this.messagesSubject.value;
  }

  get busy$(): Observable<boolean> {
    return this.busySubject.asObservable();
  }

  get busy(): boolean {
    return this.busySubject.value;
  }

  /** Sends a user message; returns false when sending is not possible. */
  send(content: string): boolean {
    const trimmed = content.trim();
    if (trimmed.length === 0 || this.busy) {
      return false;
    }
    const id = crypto.randomUUID();
    const sent = this.client.send({
      type: 'user_message',
      id,
      content: trimmed,
      lang: currentLanguage(),
      history: this.buildHistory(),
      map_context: this.mapContextProvider?.(),
    });
    if (!sent) {
      return false;
    }
    this.messagesSubject.next([
      ...this.messages,
      { role: 'user', id, content: trimmed },
      { role: 'assistant', id, status: 'streaming', steps: [] },
    ]);
    this.busySubject.next(true);
    return true;
  }

  /** Cancels the in-flight exchange, if any. */
  cancel(): void {
    const active = this.activeAssistantMessage();
    if (!active) {
      return;
    }
    this.client.send({ type: 'cancel', id: active.id });
  }

  /** Resets the conversation, stopping any in-flight exchange. */
  clear(): void {
    if (this.busy) {
      this.cancel();
    }
    this.messagesSubject.next([]);
    this.busySubject.next(false);
  }

  private activeAssistantMessage(): AssistantChatMessage | undefined {
    return this.messages.find(
      (message): message is AssistantChatMessage =>
        message.role === 'assistant' && message.status === 'streaming',
    );
  }

  private buildHistory(): HistoryEntry[] {
    const history: HistoryEntry[] = [];
    for (const message of this.messages) {
      if (message.role === 'user') {
        history.push({ role: 'user', content: message.content });
      } else if (message.status === 'complete' && message.markdown) {
        history.push({ role: 'assistant', content: message.markdown });
      }
    }
    return history.slice(-2 * HISTORY_LIMIT);
  }

  private onEvent(event: ServerEvent): void {
    switch (event.type) {
      case 'intermediate':
        this.updateAssistant(event.message_id, (message) => {
          const steps = [...message.steps];
          const index = steps.findIndex((step) => step.stepId === event.step_id);
          const step: ProgressStep = {
            stepId: event.step_id,
            status: event.status,
            label: event.label,
            detail: event.detail,
          };
          if (index >= 0) {
            steps[index] = step;
          } else {
            steps.push(step);
          }
          return { ...message, steps };
        });
        break;
      case 'final':
        this.updateAssistant(event.message_id, (message) => ({
          ...message,
          status: 'complete',
          markdown: event.content_markdown,
          layers: event.layers,
        }));
        break;
      case 'error':
        this.updateAssistant(event.message_id, (message) => ({
          ...message,
          status: event.code === 'cancelled' ? 'cancelled' : 'error',
          errorCode: event.code,
          errorMessage: event.message,
        }));
        break;
      case 'done':
        this.updateAssistant(event.message_id, (message) =>
          // Terminal without final/error (protocol violation): mark as error.
          message.status === 'streaming'
            ? {
                ...message,
                status: 'error',
                errorCode: 'internal',
                errorMessage: 'incomplete response',
              }
            : message,
        );
        this.busySubject.next(false);
        break;
    }
  }

  private updateAssistant(
    messageId: string,
    update: (message: AssistantChatMessage) => AssistantChatMessage,
  ): void {
    this.messagesSubject.next(
      this.messages.map((message) =>
        message.role === 'assistant' && message.id === messageId ? update(message) : message,
      ),
    );
  }
}
