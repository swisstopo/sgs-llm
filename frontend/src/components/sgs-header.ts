import { LitElement, css, html } from 'lit';
import { customElement } from 'lit/decorators.js';
import { ObservableController } from '../lib/ObservableController';
import { languageChanged$, t } from '../i18n/i18n';

@customElement('sgs-header')
export class SgsHeader extends LitElement {
  static override styles = css`
    :host {
      display: flex;
      align-items: center;
      gap: 1rem;
      padding: 0 1rem;
      height: 3.5rem;
      background: var(--sgc-color-bg--white, #ffffff);
      border-bottom: 1px solid var(--sgc-color-border, #d5dbe0);
    }

    .title {
      font-size: 1.125rem;
      font-weight: 700;
    }

    .title .accent {
      color: var(--sgc-color-brand, #d8232a);
    }

    .subtitle {
      color: var(--sgc-color-text--secondary, #4b5a68);
      font-size: 0.875rem;
    }
  `;

  private readonly _language = new ObservableController(this, languageChanged$);

  override render() {
    return html`
      <span class="title"><span class="accent">SGS</span> LLM</span>
      <span class="subtitle">${t('app.subtitle')}</span>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-header': SgsHeader;
  }
}
