import { LitElement, css, html } from 'lit';
import { customElement, property } from 'lit/decorators.js';
import { unsafeHTML } from 'lit/directives/unsafe-html.js';
import { Task } from '@lit/task';
import { fetchLegendHtml } from '../../swisstopo/legendApi';
import { sanitizeLegendHtml } from '../../markdown/sanitizeLegend';
import { ObservableController } from '../../lib/ObservableController';
import { currentLanguage, languageChanged$, t } from '../../i18n/i18n';

/**
 * Renders one layer's Swisstopo legend inline. The fragment is untrusted, so
 * it is sanitized (DOMPurify) before insertion; its swatch images use
 * protocol-relative URLs that resolve against the page.
 */
@customElement('sgs-legend-content')
export class SgsLegendContent extends LitElement {
  static override styles = css`
    :host {
      display: block;
      font-size: 0.75rem;
      color: var(--sgc-color-text);
    }

    .status {
      margin: 0;
      color: var(--sgc-color-text--secondary);
    }

    img {
      max-width: 100%;
      height: auto;
    }

    table {
      border-collapse: collapse;
    }

    td {
      padding: 0.0625rem 0.25rem;
      vertical-align: middle;
    }
  `;

  @property() layerId = '';

  private readonly language = new ObservableController(this, languageChanged$);

  private readonly legendTask = new Task(this, {
    args: () => [this.layerId, this.language.value ?? currentLanguage()] as const,
    task: async ([layerId, lang]) => sanitizeLegendHtml(await fetchLegendHtml(layerId, lang)),
  });

  override render() {
    return this.legendTask.render({
      pending: () => html`<p class="status">${t('legend.loading')}</p>`,
      error: () => html`<p class="status">${t('legend.error')}</p>`,
      complete: (legend) => html`${unsafeHTML(legend)}`,
    });
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-legend-content': SgsLegendContent;
  }
}
