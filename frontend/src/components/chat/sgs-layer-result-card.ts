import { LitElement, css, html, nothing } from 'lit';
import { customElement, property, state } from 'lit/decorators.js';
import type { LayerSpec } from '../../protocol/v1';
import { t } from '../../i18n/i18n';
import { isLayerExpired } from '../../map/mvtLayer';

export interface AddLayerEventDetail {
  layer: LayerSpec;
}

/**
 * Card for a data layer returned by the agent. Emits `sgs-add-layer`
 * (bubbling, composed) — the app shell decides how to put it on the map.
 */
@customElement('sgs-layer-result-card')
export class SgsLayerResultCard extends LitElement {
  static override styles = css`
    :host {
      display: block;
      border: 1px solid var(--sgc-color-border);
      border-radius: 0.375rem;
      padding: 0.625rem 0.75rem;
      background: var(--sgc-color-bg--white);
      font-size: 0.8125rem;
    }

    .name {
      font-weight: 600;
      margin: 0 0 0.125rem;
    }

    .meta {
      color: var(--sgc-color-text--secondary);
      margin: 0 0 0.5rem;
    }

    .actions {
      display: flex;
      align-items: center;
      flex-wrap: wrap;
      gap: 0.5rem;
    }

    button {
      font: inherit;
      font-size: 0.8125rem;
      padding: 0.25rem 0.625rem;
      border-radius: 0.25rem;
      border: 1px solid var(--sgc-color-brand);
      background: var(--sgc-color-brand);
      color: #fff;
      cursor: pointer;
    }

    button:disabled {
      opacity: 0.6;
      cursor: default;
    }

    .unsupported {
      color: var(--sgc-color-text--secondary);
      font-style: italic;
    }

    .warning {
      margin: 0 0 0.5rem;
      color: var(--sgc-color-text--secondary);
      font-weight: 600;
    }
  `;

  @property({ attribute: false }) layer!: LayerSpec;
  @property({ type: Boolean }) added = false;
  @state() private expired = false;

  override connectedCallback(): void {
    super.connectedCallback();
    window.addEventListener('sgs-layer-expired', this.onLayerExpired as EventListener);
  }

  override disconnectedCallback(): void {
    window.removeEventListener('sgs-layer-expired', this.onLayerExpired as EventListener);
    super.disconnectedCallback();
  }

  override render() {
    const { layer } = this;
    const renderExpired = this.expired || isLayerExpired(layer);
    const supported = layer.format === 'geojson' || (layer.format === 'mvt' && !renderExpired);
    return html`
      <p class="name">${layer.name}</p>
      <p class="meta">
        ${layer.feature_count !== undefined
          ? t('chat.featureCount', { count: layer.feature_count })
          : nothing}
        ${layer.attribution ? html` · ${layer.attribution}` : nothing}
      </p>
      ${layer.truncated
        ? html`<p class="warning" role="alert">${t('chat.truncatedLayer')}</p>`
        : nothing}
      <div class="actions">
        ${supported
          ? html`
              <button ?disabled=${this.added} @click=${this.addToMap}>
                ${this.added ? t('chat.layerAdded') : t('chat.addToMap')}
              </button>
            `
          : html`<span class="unsupported"
              >${renderExpired ? t('chat.renderExpired') : t('chat.formatUnsupported')}</span
            >`}
      </div>
    `;
  }

  private addToMap(): void {
    this.dispatchEvent(
      new CustomEvent<AddLayerEventDetail>('sgs-add-layer', {
        detail: { layer: this.layer },
        bubbles: true,
        composed: true,
      }),
    );
  }

  private readonly onLayerExpired = (event: CustomEvent<{ id: string }>): void => {
    if (event.detail.id === this.layer.id) {
      this.expired = true;
      this.added = false;
    }
  };
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-layer-result-card': SgsLayerResultCard;
  }
}
