import { LitElement, css, html } from 'lit';
import { customElement } from 'lit/decorators.js';
import { ObservableController } from '../lib/ObservableController';
import { languageChanged$, t } from '../i18n/i18n';
import './sgs-header';

@customElement('sgs-app')
export class SgsApp extends LitElement {
  static override styles = css`
    :host {
      display: grid;
      grid-template-rows: auto 1fr;
      height: 100%;
    }

    main {
      display: grid;
      place-items: center;
      gap: 1rem;
      background: var(--sgc-color-bg--grey, #f0f2f4);
    }

    .placeholder {
      display: grid;
      place-items: center;
      gap: 1rem;
      padding: 2rem;
      text-align: center;
      color: var(--sgc-color-text--secondary, #4b5a68);
    }
  `;

  // Re-render the whole shell on language change.
  private readonly _language = new ObservableController(this, languageChanged$);

  override render() {
    return html`
      <sgs-header></sgs-header>
      <main>
        <div class="placeholder">
          <p>${t('scaffold.placeholder')}</p>
          <sgc-button>${t('scaffold.action')}</sgc-button>
        </div>
      </main>
    `;
  }
}

declare global {
  interface HTMLElementTagNameMap {
    'sgs-app': SgsApp;
  }
}
