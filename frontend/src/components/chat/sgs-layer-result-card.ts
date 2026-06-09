import { LitElement, css, html, nothing } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import type { LayerSpec } from '../../protocol/v1';
import { t } from '../../i18n/i18n';

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
      border: 1px solid var(--sgc-color-border, #d5dbe0);
      border-radius: 0.375rem;
      padding: 0.625rem 0.75rem;
      background: var(--sgc-color-bg--white, #ffffff);
      font-size: 0.8125rem;
    }

    .name {
      font-weight: 600;
      margin: 0 0 0.125rem;
    }

    .meta {
      color: var(--sgc-color-text--secondary, #4b5a68);
      margin: 0 0 0.5rem;
    }

    .actions {
      display: flex;
      gap: 0.5rem;
    }

    button {
      font: inherit;
      font-size: 0.8125rem;
      padding: 0.25rem 0.625rem;
      border-radius: 0.25rem;
      border: 1px solid var(--sgc-color-brand, #d8232a);
      background: var(--sgc-color-brand, #d8232a);
      color: #fff;
      cursor: pointer;
    }

    button:disabled {
      opacity: 0.6;
      cursor: default;
    }

    .unsupported {
      color: var(--sgc-color-text--secondary, #4b5a68);
      font-style: italic;
    }
  `;

  @property({ attribute: false }) layer!: LayerSpec;
  @property({ type: Boolean }) added = false;

  override render() {
    const { layer } = this;
    const supported = layer.format === 'geojson';
    return html`
      <p class="name">${layer.name}</p>
      <p class="meta">
        ${layer.feature_count !== undefined
          ? t('chat.featureCount', { count: layer.feature_count })
          : nothing}
        ${layer.attribution ? html` · ${layer.attribution}` : nothing}
      </p>
      <div class="actions">
        ${supported
          ? html`
              <button ?disabled=${this.added} @click=${this.addToMap}>
                ${this.added ? t('chat.layerAdded') : t('chat.addToMap')}
              </button>
            `
          : html`<span class="unsupported">${t('chat.formatUnsupported')}</span>`}
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
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-layer-result-card': SgsLayerResultCard;
  }
}
