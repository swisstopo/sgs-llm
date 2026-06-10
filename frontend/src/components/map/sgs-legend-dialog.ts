import { LitElement, css, html } from 'lit';
import { customElement, property, query, state } from 'lit/decorators.js';
import { fetchLegendHtml } from '../../swisstopo/legendApi';
import { closeIcon } from '../shell/icons';
import { currentLanguage, t } from '../../i18n/i18n';

/**
 * Layer legend in a native <dialog>. Legend HTML from the API is untrusted
 * and renders only inside a sandboxed iframe; a <base> element makes the
 * protocol-relative image URLs in the fragment resolve.
 */
@customElement('sgs-legend-dialog')
export class SgsLegendDialog extends LitElement {
  static override styles = css`
    dialog {
      width: 26rem;
      max-width: 90vw;
      border: 1px solid var(--sgc-color-border);
      border-radius: 0.375rem;
      padding: 0;
      box-shadow: 0 4px 24px rgb(0 0 0 / 0.25);
    }

    dialog::backdrop {
      background: rgb(0 0 0 / 0.3);
    }

    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 0.625rem 0.875rem;
      border-bottom: 1px solid var(--sgc-color-border);
      font-weight: 600;
      font-size: 0.875rem;
    }

    .close {
      display: grid;
      place-items: center;
      border: none;
      background: none;
      cursor: pointer;
      line-height: 0;
      color: var(--sgc-color-text--secondary);
    }

    .status {
      padding: 0.875rem;
      font-size: 0.875rem;
      color: var(--sgc-color-text--secondary);
    }

    iframe {
      display: block;
      width: 100%;
      height: 60vh;
      border: none;
    }
  `;

  @property() layerLabel = '';

  @state() private legendHtml?: string;
  @state() private failed = false;

  @query('dialog') private dialog!: HTMLDialogElement;

  /** Opens the dialog and loads the legend for the given layer. */
  async open(layerId: string, layerLabel: string): Promise<void> {
    this.layerLabel = layerLabel;
    this.legendHtml = undefined;
    this.failed = false;
    this.dialog.showModal();
    try {
      this.legendHtml = await fetchLegendHtml(layerId, currentLanguage());
    } catch {
      this.failed = true;
    }
  }

  override render() {
    return html`
      <dialog @close=${() => (this.legendHtml = undefined)}>
        <header>
          <span>${this.layerLabel}</span>
          <button
            class="close"
            aria-label=${t('identify.close')}
            @click=${() => this.dialog.close()}
          >
            ${closeIcon}
          </button>
        </header>
        ${this.failed
          ? html`<p class="status">${t('legend.error')}</p>`
          : this.legendHtml === undefined
            ? html`<p class="status">${t('legend.loading')}</p>`
            : html`<iframe
                sandbox=""
                title=${this.layerLabel}
                srcdoc=${`<base href="https://api3.geo.admin.ch/">` + this.legendHtml}
              ></iframe>`}
      </dialog>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-legend-dialog': SgsLegendDialog;
  }
}
