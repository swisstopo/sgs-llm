import { LitElement, css, html, nothing } from 'lit';
import { customElement, property, state } from 'lit/decorators.js';
import { unsafeHTML } from 'lit/directives/unsafe-html.js';
import type { ChatMessage } from '../../services/ChatService';
import type { CatalogLayerRef } from '../../protocol/v1';
import { mentionedCatalogLayers, renderMarkdown } from '../../markdown/renderMarkdown';
import { t } from '../../i18n/i18n';
import type {
  AddCatalogLayerEventDetail,
  OpenCatalogLayerEventDetail,
  RemoveCatalogLayerEventDetail,
} from './sgs-catalog-layer-card';
import './sgs-progress-steps';
import './sgs-layer-result-card';
import './sgs-catalog-layer-card';

/** One chat exchange entry: a user bubble or a streamed assistant answer. */
@customElement('sgs-chat-message')
export class SgsChatMessage extends LitElement {
  static override styles = css`
    :host {
      display: block;
      min-width: 0;
      max-width: 100%;
    }

    .user {
      margin-left: 20%;
      background: var(--sgc-color-brand);
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
      position: relative;
      min-width: 0;
      max-width: 100%;
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
      color: var(--sgc-color-brand);
    }

    .markdown code {
      background: var(--sgc-color-bg--grey);
      padding: 0.0625rem 0.25rem;
      border-radius: 0.25rem;
      font-size: 0.8125rem;
    }

    .markdown button.inline-catalog-layer {
      appearance: none;
      border: 0;
      border-bottom: 1px dashed currentColor;
      padding: 0;
      background: transparent;
      color: var(--sgc-color-brand);
      font: inherit;
      font-weight: 600;
      cursor: pointer;
    }

    .markdown button.inline-catalog-layer:hover,
    .markdown button.inline-catalog-layer:focus-visible {
      border-bottom-style: solid;
    }

    .layer-choice {
      position: absolute;
      z-index: 20;
      box-sizing: border-box;
      width: min(18rem, calc(100% - 0.5rem));
      transform: translateY(calc(-100% - 0.5rem));
      padding: 0.625rem 0.75rem;
      border: 1px solid var(--sgc-color-border);
      border-radius: 0.375rem;
      background: var(--sgc-color-bg--white);
      box-shadow: 0 0.25rem 0.75rem rgb(0 0 0 / 12%);
      font-size: 0.8125rem;
    }

    .layer-choice::after {
      content: '';
      position: absolute;
      top: 100%;
      left: 1rem;
      border: 0.375rem solid transparent;
      border-top-color: var(--sgc-color-border);
    }

    .layer-choice .close {
      position: absolute;
      top: 0.25rem;
      right: 0.25rem;
      display: grid;
      place-items: center;
      width: 1.75rem;
      height: 1.75rem;
      border: 0;
      padding: 0;
      background: transparent;
      color: var(--sgc-color-text--secondary);
      font-size: 1.25rem;
      line-height: 1;
    }

    .layer-choice .close:hover {
      color: var(--sgc-color-text);
      background: var(--sgc-color-bg--grey);
    }

    .layer-choice .title {
      margin: 0 2rem 0.25rem 0;
      font-weight: 600;
    }

    .layer-choice .metadata {
      margin: 0 2rem 0.625rem 0;
      color: var(--sgc-color-text--secondary);
      font-size: 0.75rem;
      overflow-wrap: anywhere;
    }

    .layer-choice .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 0.5rem;
    }

    .layer-choice button {
      border: 1px solid var(--sgc-color-brand);
      border-radius: 0.25rem;
      padding: 0.25rem 0.625rem;
      background: var(--sgc-color-brand);
      color: #fff;
      font: inherit;
      cursor: pointer;
    }

    .layer-choice button.secondary {
      background: var(--sgc-color-bg--white);
      color: var(--sgc-color-brand);
    }

    .markdown table {
      border-collapse: collapse;
      margin: 0.5rem 0;
    }

    .markdown th,
    .markdown td {
      border: 1px solid var(--sgc-color-border);
      padding: 0.25rem 0.5rem;
      text-align: left;
    }

    .error {
      color: var(--sgc-color-brand);
      font-size: 0.875rem;
    }

    .cancelled {
      color: var(--sgc-color-text--secondary);
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
  @state() private selectedCatalogLayerId?: string;
  @state() private layerChoicePosition?: { left: number; top: number };

  override render() {
    const { message } = this;
    if (message.role === 'user') {
      return html`<div class="user">${message.content}</div>`;
    }
    const catalogLayers = message.catalogLayers ?? [];
    const inlineLayers = mentionedCatalogLayers(message.markdown ?? '', catalogLayers);
    const selectedLayer = catalogLayers.find((layer) => layer.id === this.selectedCatalogLayerId);
    return html`
      <div class="assistant">
        ${message.steps.length > 0
          ? html`<sgs-progress-steps .steps=${message.steps}></sgs-progress-steps>`
          : nothing}
        ${message.markdown
          ? html`<div class="markdown" @click=${this.onMarkdownClick}>
              ${unsafeHTML(renderMarkdown(message.markdown, inlineLayers))}
            </div>`
          : nothing}
        ${selectedLayer && this.layerChoicePosition
          ? this.renderLayerChoice(selectedLayer, this.layerChoicePosition)
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
        ${catalogLayers.length > 0 && inlineLayers.length === 0
          ? html`
              <div class="layers">
                ${catalogLayers.map(
                  (layer) => html`
                    <sgs-catalog-layer-card
                      .layer=${layer}
                      .focusBBox=${message.focusBBox}
                      ?added=${this.addedLayerIds.has(layer.id)}
                    ></sgs-catalog-layer-card>
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

  private onMarkdownClick(event: MouseEvent): void {
    const target = event.target;
    if (!(target instanceof HTMLButtonElement)) {
      return;
    }
    const id = target.dataset.catalogLayerId;
    const message = this.message;
    if (
      message.role === 'assistant' &&
      id &&
      message.catalogLayers?.some((layer) => layer.id === id)
    ) {
      if (this.selectedCatalogLayerId === id) {
        this.closeLayerChoice();
        return;
      }
      const assistant = this.renderRoot.querySelector<HTMLElement>('.assistant');
      if (!assistant) {
        return;
      }
      const targetRect = target.getBoundingClientRect();
      const assistantRect = assistant.getBoundingClientRect();
      const rootFontSize = Number.parseFloat(getComputedStyle(document.documentElement).fontSize);
      const menuWidth = Math.min(
        18 * (Number.isFinite(rootFontSize) ? rootFontSize : 16),
        Math.max(0, assistantRect.width - 8),
      );
      const requestedLeft = targetRect.left - assistantRect.left;
      const maximumLeft = Math.max(4, assistantRect.width - menuWidth - 4);
      this.layerChoicePosition = {
        left: Math.min(Math.max(4, requestedLeft), maximumLeft),
        top: targetRect.top - assistantRect.top,
      };
      this.selectedCatalogLayerId = id;
    }
  }

  private renderLayerChoice(layer: CatalogLayerRef, position: { left: number; top: number }) {
    const added = this.addedLayerIds.has(layer.id);
    return html`
      <div
        class="layer-choice"
        role="dialog"
        aria-label=${layer.name || layer.id}
        style=${`left: ${position.left}px; top: ${position.top}px`}
      >
        <button
          class="close"
          aria-label=${t('chat.closeLayerMenu')}
          title=${t('chat.closeLayerMenu')}
          @click=${this.closeLayerChoice}
        >
          ×
        </button>
        <p class="title">${layer.name || layer.id}</p>
        <p class="metadata">${layer.attribution || 'geo.admin.ch'}<br />${layer.id}</p>
        <div class="actions">
          <button @click=${() => this.toggleCatalogLayer(layer, added)}>
            ${added ? t('chat.removeOfficialLayer') : t('chat.addOfficialLayer')}
          </button>
          <button class="secondary" @click=${() => this.openCatalogLayer(layer)}>
            ${t('chat.layerDetails')}
          </button>
        </div>
      </div>
    `;
  }

  private toggleCatalogLayer(layer: CatalogLayerRef, added: boolean): void {
    if (added) {
      this.dispatchEvent(
        new CustomEvent<RemoveCatalogLayerEventDetail>('sgs-remove-catalog-layer', {
          detail: { id: layer.id },
          bubbles: true,
          composed: true,
        }),
      );
      this.closeLayerChoice();
      return;
    }
    this.addCatalogLayer(layer);
  }

  private closeLayerChoice(): void {
    this.selectedCatalogLayerId = undefined;
    this.layerChoicePosition = undefined;
  }

  private addCatalogLayer(layer: CatalogLayerRef): void {
    const message = this.message;
    if (message.role !== 'assistant') {
      return;
    }
    this.dispatchEvent(
      new CustomEvent<AddCatalogLayerEventDetail>('sgs-add-catalog-layer', {
        detail: { layer, focusBBox: message.focusBBox },
        bubbles: true,
        composed: true,
      }),
    );
  }

  private openCatalogLayer(layer: CatalogLayerRef): void {
    this.dispatchEvent(
      new CustomEvent<OpenCatalogLayerEventDetail>('sgs-open-catalog-layer', {
        detail: { id: layer.id, label: layer.name },
        bubbles: true,
        composed: true,
      }),
    );
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-chat-message': SgsChatMessage;
  }
}
