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
      background: var(--sgc-color-bg--grey);
    }

    .messages {
      overflow-y: auto;
      padding: 1rem;
      display: grid;
      gap: 0.875rem;
      align-content: start;
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

  private readonly _language = new ObservableController(this, languageChanged$);

  override connectedCallback(): void {
    super.connectedCallback();
    this.messages ??= new ObservableController(this, this.chatService.messages$);
    this.busy ??= new ObservableController(this, this.chatService.busy$);
    this.model ??= new ObservableController(this, this.chatService.model$);
    this.mapLayers ??= new ObservableController(this, this.layerService.layers$);
  }

  override render() {
    const messages = this.messages?.value ?? [];
    const addedLayerIds = new Set((this.mapLayers?.value ?? []).map((layer) => layer.id));
    return html`
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
                  .addedLayerIds=${addedLayerIds}
                ></sgs-chat-message>
              `,
            )}
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
