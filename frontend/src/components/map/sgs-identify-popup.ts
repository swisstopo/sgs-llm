import { LitElement, css, html, nothing } from 'lit';
import { customElement, property, state } from 'lit/decorators.js';
import type { IdentifyFeature } from '../../swisstopo/identifyApi';
import { htmlPopupUrl } from '../../swisstopo/identifyApi';
import { formatLV95 } from '../../lib/projection';
import { closeIcon } from '../shell/icons';
import { currentLanguage, t } from '../../i18n/i18n';

/**
 * Identify result list anchored at the click point (via ol/Overlay).
 * Feature details (htmlPopup) are untrusted HTML and load only inside a
 * sandboxed iframe.
 */
@customElement('sgs-identify-popup')
export class SgsIdentifyPopup extends LitElement {
  static override styles = css`
    :host {
      display: block;
      width: 20rem;
      max-width: 70vw;
      background: var(--sgc-color-bg--white);
      border: 1px solid var(--sgc-color-border);
      border-radius: 0.375rem;
      box-shadow: 0 2px 10px rgb(0 0 0 / 0.25);
      font-size: 0.8125rem;
      transform: translate(-50%, calc(-100% - 12px));
    }

    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 0.5rem;
      padding: 0.5rem 0.625rem;
      border-bottom: 1px solid var(--sgc-color-border);
    }

    .coords {
      color: var(--sgc-color-text--secondary);
      font-size: 0.6875rem;
    }

    .close {
      display: grid;
      place-items: center;
      border: none;
      background: none;
      cursor: pointer;
      padding: 0.125rem 0.25rem;
      line-height: 0;
      color: var(--sgc-color-text--secondary);
    }

    .body {
      max-height: 19rem;
      overflow-y: auto;
      padding: 0.375rem 0;
    }

    .status {
      padding: 0.375rem 0.625rem;
      color: var(--sgc-color-text--secondary);
    }

    .feature-button {
      display: block;
      width: 100%;
      border: none;
      background: none;
      text-align: left;
      font: inherit;
      font-size: 0.8125rem;
      padding: 0.375rem 0.625rem;
      cursor: pointer;
    }

    .feature-button:hover {
      background: var(--sgc-color-bg--grey);
    }

    .feature-button .layer {
      display: block;
      font-size: 0.6875rem;
      color: var(--sgc-color-text--secondary);
    }

    iframe {
      display: block;
      width: 100%;
      height: 14rem;
      border: none;
      border-top: 1px solid var(--sgc-color-border);
    }
  `;

  @property({ attribute: false }) features: IdentifyFeature[] = [];
  @property({ type: Boolean }) loading = false;
  @property({ attribute: false }) coordinate?: [number, number];

  @state() private expandedKey?: string;

  override willUpdate(): void {
    // Collapse details whenever a new identify result arrives.
    if (this.loading) {
      this.expandedKey = undefined;
    }
  }

  override render() {
    return html`
      <header>
        <span class="coords">
          ${this.coordinate ? html`LV95 ${formatLV95(this.coordinate)}` : nothing}
        </span>
        <button class="close" aria-label=${t('identify.close')} @click=${this.close}>
          ${closeIcon}
        </button>
      </header>
      <div class="body">
        ${this.loading
          ? html`<p class="status">${t('identify.loading')}</p>`
          : this.features.length === 0
            ? html`<p class="status">${t('identify.empty')}</p>`
            : this.features.map((feature) => this.renderFeature(feature))}
      </div>
    `;
  }

  private renderFeature(feature: IdentifyFeature) {
    const key = `${feature.layerBodId}/${feature.featureId}`;
    const expanded = this.expandedKey === key;
    return html`
      <button
        class="feature-button"
        aria-expanded=${expanded}
        @click=${() => (this.expandedKey = expanded ? undefined : key)}
      >
        ${feature.label}
        <span class="layer">${feature.layerName}</span>
      </button>
      ${expanded
        ? html`<iframe
            sandbox=""
            title=${feature.label}
            src=${htmlPopupUrl(feature.layerBodId, feature.featureId, currentLanguage())}
          ></iframe>`
        : nothing}
    `;
  }

  private close(): void {
    this.dispatchEvent(new CustomEvent('sgs-close', { bubbles: true, composed: true }));
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-identify-popup': SgsIdentifyPopup;
  }
}
