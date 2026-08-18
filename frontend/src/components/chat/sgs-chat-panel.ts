import { LitElement, css, html } from 'lit';
import { customElement } from 'lit/decorators.js';
import { consume } from '@lit/context';
import { chatServiceContext, layerServiceContext } from '../../context';
import type { ChatMessage, ChatService } from '../../services/ChatService';
import type { LayerService, MapLayerState } from '../../services/LayerService';
import type { ModelPreference } from '../../protocol/v1';
import { ObservableController } from '../../lib/ObservableController';
import { languageChanged$, t } from '../../i18n/i18n';
import './sgs-chat-message';
import './sgs-composer';

/** Chat panel body: message list + composer (title/badge live in the flyout header). */
@customElement('sgs-chat-panel')
export class SgsChatPanel extends LitElement {
  static override styles = css`
    :host {
      display: grid;
      grid-template-rows: 1fr auto;
      height: 100%;
      min-height: 0;
      min-width: 0;
      background: var(--sgc-color-bg--grey);
    }

    .messages {
      overflow-y: auto;
      overflow-x: hidden;
      min-width: 0;
      padding: 1rem;
    }

    .message-stack {
      display: grid;
      gap: 0.875rem;
      align-content: start;
      min-width: 0;
      max-width: 100%;
    }

    .welcome {
      color: var(--sgc-color-text--secondary);
      font-size: 0.875rem;
      line-height: 1.5;
    }

    .welcome ul {
      margin: 0.5rem 0 0;
      padding-left: 1.25rem;
    }

    footer {
      padding: 0.75rem 1rem;
      border-top: 1px solid var(--sgc-color-border);
      background: var(--sgc-color-bg--white);
    }
  `;

  @consume({ context: chatServiceContext })
  private chatService!: ChatService;

  @consume({ context: layerServiceContext })
  private layerService!: LayerService;

  private messages?: ObservableController<ChatMessage[]>;
  private busy?: ObservableController<boolean>;
  private model?: ObservableController<ModelPreference>;
  private mapLayers?: ObservableController<MapLayerState[]>;
  private messageStackObserver?: ResizeObserver;
  private observedMessageStack?: HTMLElement;
  private scrollFrame?: number;
  private followLatest = true;

  private readonly _language = new ObservableController(this, languageChanged$);

  override connectedCallback(): void {
    super.connectedCallback();
    this.messages ??= new ObservableController(this, this.chatService.messages$);
    this.busy ??= new ObservableController(this, this.chatService.busy$);
    this.model ??= new ObservableController(this, this.chatService.model$);
    this.mapLayers ??= new ObservableController(this, this.layerService.layers$);
  }

  override disconnectedCallback(): void {
    this.messageStackObserver?.disconnect();
    this.observedMessageStack = undefined;
    if (this.scrollFrame !== undefined) {
      cancelAnimationFrame(this.scrollFrame);
      this.scrollFrame = undefined;
    }
    super.disconnectedCallback();
  }

  override render() {
    const messages = this.messages?.value ?? [];
    const addedLayerIds = new Set((this.mapLayers?.value ?? []).map((layer) => layer.id));
    return html`
      <div class="messages" @scroll=${this.onMessagesScroll}>
        <div class="message-stack">
          ${messages.length === 0
            ? html`
                <div class="welcome">
                  <p>${t('chat.welcome')}</p>
                  <ul>
                    <li>${t('chat.exampleFlood')}</li>
                    <li>${t('chat.exampleSolar')}</li>
                  </ul>
                </div>
              `
            : messages.map(
                (message) => html`
                  <sgs-chat-message
                    .message=${message}
                    .addedLayerIds=${addedLayerIds}
                  ></sgs-chat-message>
                `,
              )}
        </div>
      </div>
      <footer>
        <sgs-composer
          ?busy=${this.busy?.value ?? false}
          .model=${this.model?.value ?? 'primary'}
          @sgs-model-change=${(e: CustomEvent<{ model: ModelPreference }>) =>
            this.chatService.selectModel(e.detail.model)}
          @sgs-send=${(e: CustomEvent<{ content: string }>) =>
            this.chatService.send(e.detail.content)}
          @sgs-cancel=${() => this.chatService.cancel()}
        ></sgs-composer>
      </footer>
    `;
  }

  override updated(): void {
    const stack = this.renderRoot.querySelector<HTMLElement>('.message-stack');
    if (stack && stack !== this.observedMessageStack && typeof ResizeObserver !== 'undefined') {
      this.messageStackObserver?.disconnect();
      this.messageStackObserver = new ResizeObserver(() => this.scrollToLatest());
      this.messageStackObserver.observe(stack);
      this.observedMessageStack = stack;
    }
    this.scrollToLatest();
  }

  private onMessagesScroll(event: Event): void {
    const container = event.currentTarget as HTMLElement;
    const distanceFromBottom = container.scrollHeight - container.scrollTop - container.clientHeight;
    this.followLatest = distanceFromBottom <= 48;
  }

  private scrollToLatest(): void {
    if (!this.followLatest || this.scrollFrame !== undefined) {
      return;
    }
    this.scrollFrame = requestAnimationFrame(() => {
      this.scrollFrame = undefined;
      const container = this.renderRoot.querySelector<HTMLElement>('.messages');
      if (container && this.followLatest) {
        container.scrollTop = container.scrollHeight;
      }
    });
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-chat-panel': SgsChatPanel;
  }
}
