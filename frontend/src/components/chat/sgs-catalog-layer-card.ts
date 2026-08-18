import { LitElement, css, html, nothing } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import type { CatalogLayerRef, ProtocolBBox } from '../../protocol/v1';
import { t } from '../../i18n/i18n';

export interface AddCatalogLayerEventDetail {
  layer: CatalogLayerRef;
  focusBBox?: ProtocolBBox;
}

export interface OpenCatalogLayerEventDetail {
  id: string;
  label?: string;
}

export interface RemoveCatalogLayerEventDetail {
  id: string;
}

/** A user-controlled action for a layer whose tiles stay on geo.admin.ch. */
@customElement('sgs-catalog-layer-card')
export class SgsCatalogLayerCard extends LitElement {
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

    .kind {
      color: var(--sgc-color-text--secondary);
      font-size: 0.6875rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      margin: 0 0 0.25rem;
      text-transform: uppercase;
    }

    .id {
      color: var(--sgc-color-text--secondary);
      margin: 0 0 0.5rem;
      overflow-wrap: anywhere;
    }

    .actions {
      display: flex;
      gap: 0.5rem;
      flex-wrap: wrap;
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

    button.secondary {
      color: var(--sgc-color-brand);
      background: var(--sgc-color-bg--white);
    }
  `;

  @property({ attribute: false }) layer!: CatalogLayerRef;
  @property({ attribute: false }) focusBBox?: ProtocolBBox;
  @property({ type: Boolean }) added = false;

  override render() {
    return html`
      <p class="kind">${t('chat.officialLayer')}</p>
      <p class="name">${this.layer.name || this.layer.id}</p>
      <p class="id">
        ${this.layer.id}${this.layer.attribution ? html` · ${this.layer.attribution}` : nothing}
      </p>
      <div class="actions">
        <button @click=${this.toggleMap}>
          ${this.added ? t('chat.removeOfficialLayer') : t('chat.addOfficialLayer')}
        </button>
        <button class="secondary" @click=${this.openDetails}>${t('chat.layerDetails')}</button>
      </div>
    `;
  }

  private toggleMap(): void {
    if (this.added) {
      this.dispatchEvent(
        new CustomEvent<RemoveCatalogLayerEventDetail>('sgs-remove-catalog-layer', {
          detail: { id: this.layer.id },
          bubbles: true,
          composed: true,
        }),
      );
      return;
    }
    this.dispatchEvent(
      new CustomEvent<AddCatalogLayerEventDetail>('sgs-add-catalog-layer', {
        detail: { layer: this.layer, focusBBox: this.focusBBox },
        bubbles: true,
        composed: true,
      }),
    );
  }

  private openDetails(): void {
    this.dispatchEvent(
      new CustomEvent<OpenCatalogLayerEventDetail>('sgs-open-catalog-layer', {
        detail: { id: this.layer.id, label: this.layer.name },
        bubbles: true,
        composed: true,
      }),
    );
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-catalog-layer-card': SgsCatalogLayerCard;
  }
}
