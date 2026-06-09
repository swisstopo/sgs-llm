import { LitElement, css, html, nothing } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { unsafeHTML } from 'lit/directives/unsafe-html.js';
import type { ChatMessage } from '../../services/ChatService';
import { renderMarkdown } from '../../markdown/renderMarkdown';
import { t } from '../../i18n/i18n';
import './sgs-progress-steps';
import './sgs-layer-result-card';

/** One chat exchange entry: a user bubble or a streamed assistant answer. */
@customElement('sgs-chat-message')
export class SgsChatMessage extends LitElement {
  static override styles = css`
    :host {
      display: block;
    }

    .user {
      margin-left: 20%;
      background: var(--sgc-color-brand, #d8232a);
      color: #fff;
      border-radius: 0.75rem 0.75rem 0.25rem 0.75rem;
      padding: 0.625rem 0.875rem;
      font-size: 0.875rem;
      white-space: pre-wrap;
      overflow-wrap: anywhere;
    }

    .assistant {
      margin-right: 10%;
      display: grid;
      gap: 0.625rem;
    }

    /* Markdown typography must live here: sanitized HTML gets no global styles. */
    .markdown {
      font-size: 0.875rem;
      line-height: 1.55;
      overflow-wrap: anywhere;
    }

    .markdown > :first-child {
      margin-top: 0;
    }

    .markdown > :last-child {
      margin-bottom: 0;
    }

    .markdown h1,
    .markdown h2,
    .markdown h3 {
      font-size: 1rem;
      margin: 0.75rem 0 0.375rem;
    }

    .markdown p,
    .markdown ul,
    .markdown ol {
      margin: 0.375rem 0;
    }

    .markdown a {
      color: var(--sgc-color-brand, #d8232a);
    }

    .markdown code {
      background: var(--sgc-color-bg--grey, #f0f2f4);
      padding: 0.0625rem 0.25rem;
      border-radius: 0.25rem;
      font-size: 0.8125rem;
    }

    .markdown table {
      border-collapse: collapse;
      margin: 0.5rem 0;
    }

    .markdown th,
    .markdown td {
      border: 1px solid var(--sgc-color-border, #d5dbe0);
      padding: 0.25rem 0.5rem;
      text-align: left;
    }

    .error {
      color: var(--sgc-color-brand, #d8232a);
      font-size: 0.875rem;
    }

    .cancelled {
      color: var(--sgc-color-text--secondary, #4b5a68);
      font-size: 0.875rem;
      font-style: italic;
    }

    .layers {
      display: grid;
      gap: 0.5rem;
    }
  `;

  @property({ attribute: false }) message!: ChatMessage;
  /** Ids of data layers already added to the map. */
  @property({ attribute: false }) addedLayerIds: ReadonlySet<string> = new Set();

  override render() {
    const { message } = this;
    if (message.role === 'user') {
      return html`<div class="user">${message.content}</div>`;
    }
    return html`
      <div class="assistant">
        ${message.steps.length > 0
          ? html`<sgs-progress-steps .steps=${message.steps}></sgs-progress-steps>`
          : nothing}
        ${message.markdown
          ? html`<div class="markdown">${unsafeHTML(renderMarkdown(message.markdown))}</div>`
          : nothing}
        ${message.layers && message.layers.length > 0
          ? html`
              <div class="layers">
                ${message.layers.map(
                  (layer) => html`
                    <sgs-layer-result-card
                      .layer=${layer}
                      ?added=${this.addedLayerIds.has(layer.id)}
                    ></sgs-layer-result-card>
                  `,
                )}
              </div>
            `
          : nothing}
        ${message.status === 'error'
          ? html`<p class="error">
              ${t('chat.error')}${message.errorMessage ? html` (${message.errorMessage})` : nothing}
            </p>`
          : nothing}
        ${message.status === 'cancelled'
          ? html`<p class="cancelled">${t('chat.cancelled')}</p>`
          : nothing}
      </div>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-chat-message': SgsChatMessage;
  }
}
