import { LitElement, css, html, nothing } from 'lit';
import { customElement, property, state } from 'lit/decorators.js';
import type { IdentifyFeature } from '../../swisstopo/identifyApi';
import { htmlPopupUrl } from '../../swisstopo/identifyApi';
import { displayProperties } from '../../map/featureInfo';
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
    /* No transform: ol/Overlay places this via the anchor's positioning, which is
       recomputed on every resize so the popup flips below the click near the top edge. */
    :host {
      display: block;
      position: relative;
      width: 100%;
      background: var(--sgc-color-bg--white);
      border: 1px solid var(--sgc-color-border);
      border-radius: 0.375rem;
      box-shadow: 0 2px 10px rgb(0 0 0 / 0.25);
      font-size: 0.8125rem;
    }

    /* Floats over the first row rather than owning a header strip of its own - with the
       coordinates gone there was nothing else to put on that row. */
    .close {
      position: absolute;
      top: 0.25rem;
      right: 0.25rem;
      z-index: 1;
      display: grid;
      place-items: center;
      border: none;
      border-radius: 0.25rem;
      background: none;
      cursor: pointer;
      padding: 0.25rem;
      line-height: 0;
      color: var(--sgc-color-text--secondary);
    }

    .close:hover {
      background: var(--sgc-color-bg--grey);
      color: var(--sgc-color-text);
    }

    .body {
      max-height: 19rem;
      overflow-y: auto;
      padding: 0.25rem 0;
    }

    .status {
      padding: 0.375rem 2rem 0.375rem 0.625rem;
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
      /* Right pad keeps the label clear of the close button floating above it. */
      padding: 0.375rem 2rem 0.375rem 0.625rem;
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

    dl.props {
      display: grid;
      grid-template-columns: minmax(5rem, auto) 1fr;
      gap: 0.125rem 0.5rem;
      margin: 0;
      padding: 0.375rem 0.625rem 0.5rem;
      border-top: 1px solid var(--sgc-color-border);
    }

    dl.props dt {
      color: var(--sgc-color-text--secondary);
      font-size: 0.6875rem;
      overflow-wrap: anywhere;
    }

    dl.props dd {
      margin: 0;
      overflow-wrap: anywhere;
    }
  `;

  @property({ attribute: false }) features: IdentifyFeature[] = [];
  @property({ type: Boolean }) loading = false;

  @state() private expandedKey?: string;

  override willUpdate(): void {
    // Collapse details whenever a new identify result arrives.
    if (this.loading) {
      this.expandedKey = undefined;
      return;
    }
    // A lone client-side hit expands itself: its attributes are already in memory, so
    // hiding them behind a second click buys nothing. Identify results stay collapsed —
    // expanding one of those fetches an htmlPopup fragment.
    const only = this.features.length === 1 ? this.features[0] : undefined;
    if (only?.properties) {
      this.expandedKey = `${only.layerBodId}/${only.featureId}`;
    }
  }

  override render() {
    return html`
      <button class="close" aria-label=${t('identify.close')} @click=${this.close}>
        ${closeIcon}
      </button>
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
      ${expanded ? this.renderDetails(feature) : nothing}
    `;
  }

  /**
   * Client-side hits carry their own attributes and are rendered here as text. Only
   * swisstopo's identify results fall through to the htmlPopup fragment, which is
   * untrusted HTML and therefore only ever loads inside a sandboxed iframe.
   */
  private renderDetails(feature: IdentifyFeature) {
    if (!feature.properties) {
      return html`<iframe
        sandbox=""
        title=${feature.label}
        src=${htmlPopupUrl(feature.layerBodId, feature.featureId, currentLanguage())}
      ></iframe>`;
    }
    const rows = displayProperties(feature.properties);
    if (rows.length === 0) {
      return html`<p class="status">${t('identify.noAttributes')}</p>`;
    }
    return html`
      <dl class="props">
        ${rows.map(
          ([key, value]) =>
            html`<dt>${key}</dt>
              <dd>${value}</dd>`,
        )}
      </dl>
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
