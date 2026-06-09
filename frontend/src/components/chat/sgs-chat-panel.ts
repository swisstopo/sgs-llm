import { LitElement, css, html } from 'lit';
import { customElement, state } from 'lit/decorators.js';
import { consume } from '@lit/context';
import { chatServiceContext } from '../../context';
import type { ChatMessage, ChatService } from '../../services/ChatService';
import { ObservableController } from '../../lib/ObservableController';
import { languageChanged$, t } from '../../i18n/i18n';
import './sgs-chat-message';
import './sgs-composer';
import './sgs-connection-badge';

/** Chat column: header with connection badge, message list, composer. */
@customElement('sgs-chat-panel')
export class SgsChatPanel extends LitElement {
  static override styles = css`
    :host {
      display: grid;
      grid-template-rows: auto 1fr auto;
      height: 100%;
      min-height: 0;
      background: var(--sgc-color-bg--grey, #f0f2f4);
      border-right: 1px solid var(--sgc-color-border, #d5dbe0);
    }

    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0.625rem 1rem;
      border-bottom: 1px solid var(--sgc-color-border, #d5dbe0);
      background: var(--sgc-color-bg--white, #ffffff);
      font-size: 0.875rem;
      font-weight: 600;
    }

    .messages {
      overflow-y: auto;
      padding: 1rem;
      display: grid;
      gap: 0.875rem;
      align-content: start;
    }

    .welcome {
      color: var(--sgc-color-text--secondary, #4b5a68);
      font-size: 0.875rem;
      line-height: 1.5;
    }

    .welcome ul {
      margin: 0.5rem 0 0;
      padding-left: 1.25rem;
    }

    footer {
      padding: 0.75rem 1rem;
      border-top: 1px solid var(--sgc-color-border, #d5dbe0);
      background: var(--sgc-color-bg--white, #ffffff);
    }
  `;

  @consume({ context: chatServiceContext })
  private chatService!: ChatService;

  @state() private addedLayerIds: ReadonlySet<string> = new Set();

  private messages?: ObservableController<ChatMessage[]>;
  private busy?: ObservableController<boolean>;

  private readonly _language = new ObservableController(this, languageChanged$);

  override connectedCallback(): void {
    super.connectedCallback();
    this.messages ??= new ObservableController(this, this.chatService.messages$);
    this.busy ??= new ObservableController(this, this.chatService.busy$);
  }

  /** Called by the app shell when a chat data layer lands on the map. */
  markLayerAdded(layerId: string): void {
    this.addedLayerIds = new Set([...this.addedLayerIds, layerId]);
  }

  override render() {
    const messages = this.messages?.value ?? [];
    return html`
      <header>
        <span>${t('chat.title')}</span>
        <sgs-connection-badge></sgs-connection-badge>
      </header>
      <div class="messages">
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
                  .addedLayerIds=${this.addedLayerIds}
                ></sgs-chat-message>
              `,
            )}
      </div>
      <footer>
        <sgs-composer
          ?busy=${this.busy?.value ?? false}
          @sgs-send=${(e: CustomEvent<{ content: string }>) =>
            this.chatService.send(e.detail.content)}
          @sgs-cancel=${() => this.chatService.cancel()}
        ></sgs-composer>
      </footer>
    `;
  }

  override updated(): void {
    // Keep the newest message in view while streaming.
    const container = this.renderRoot.querySelector('.messages');
    if (container) {
      container.scrollTop = container.scrollHeight;
    }
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-chat-panel': SgsChatPanel;
  }
}
